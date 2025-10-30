import logging
import pickle
import subprocess
import sys
import typing as T
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QDataStream, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from tqdm import tqdm

from pupil_labs import neon_player


@dataclass
class ProgressUpdate:
    progress: float = 0.0
    datum: T.Any = None


class BackgroundJob(QObject):
    progress_changed = Signal(float)
    finished = Signal()
    canceled = Signal()

    def __init__(
        self,
        name: str,
        job_id: int,
        recording_path: Path,
        action_name: str,
        *args: T.Any,
    ):
        super().__init__()

        self.name = name
        self.job_id = job_id
        self.progress = -1
        self.socket = None

        server_name = f"neon-player-job-{job_id}"
        self.server = QLocalServer()
        QLocalServer.removeServer(server_name)  # remove any dangling sockets
        if not self.server.listen(server_name):
            logging.error(f"Could not start IPC server for job {name}")
            return

        self.server.newConnection.connect(self._handle_connection)

        args = (
            [
                str(recording_path),
                "--progress-ipc-name",
                server_name,
                "--job",
                action_name,
            ]
            + [str(arg) for arg in args]
        )

        if neon_player.is_frozen():
            cmd = [sys.executable] + args
        else:
            cmd = [sys.executable, "-m", "pupil_labs.neon_player"] + args

        logging.debug(f"Executing bg job {' '.join(cmd)}")

        self.proc = subprocess.Popen(cmd)

        logging.info(f"Background job started: {self.name}")

    def _handle_connection(self):
        self.socket = self.server.nextPendingConnection()
        self.socket.readyRead.connect(self._read_progress_update)
        self.socket.disconnected.connect(self.finished.emit)
        self.server.close()

    def _read_progress_update(self):
        if not self.socket:
            return

        stream = QDataStream(self.socket)
        while self.socket.bytesAvailable() >= 4:
            # Read the length of the data
            expected_len = stream.readUInt32()

            # Wait until all data is available
            if self.socket.bytesAvailable() < expected_len:
                return

            # Read and unpickle the data
            data = stream.readRawData(expected_len)
            try:
                obj = pickle.loads(data)
                self.progress_changed.emit(obj.progress)
                self.progress = obj.progress
            except Exception:
                logging.exception("Could not unpickle progress update")

    def cancel(self):
        self.proc.terminate()
        self.proc.wait()


class JobManager(QObject):
    updated = Signal()
    job_started = Signal(BackgroundJob)
    job_finished = Signal(BackgroundJob)
    job_canceled = Signal(BackgroundJob)

    def __init__(self):
        super().__init__()
        self.current_jobs = []
        self.job_counter = 0

    def work_job(self, job: T.Generator[ProgressUpdate, None, None]) -> None:
        ipc_name = neon_player.instance().progress_ipc_name
        # runs in child process
        if ipc_name:
            socket = QLocalSocket()
            socket.connectToServer(ipc_name)
            if not socket.waitForConnected(1000):
                logging.error(f"Could not connect to IPC server {ipc_name}")
                return

            if not hasattr(job, "__iter__"):
                logging.warning(f"A background job did not generate progress updates")
            else:
                outstream = QDataStream(socket)
                for update in job:
                    data = pickle.dumps(update)
                    outstream.writeUInt32(len(data))
                    outstream.writeRawData(data)
                    socket.flush()

            socket.disconnectFromServer()

        else:
            with tqdm(total=1.0) as pbar:
                for update in job:
                    pbar.n = update.progress
                    pbar.refresh()

    def run_background_action(self, name: str, action_name: str, *args: T.Any) -> BackgroundJob:
        if neon_player.instance().headless:
            logging.warning("Not starting background job in headless mode")
            return

        neon_player.instance().save_settings()

        job = BackgroundJob(
            name,
            self.job_counter,
            neon_player.instance().recording._rec_dir,
            action_name,
            *args
        )
        self.job_counter += 1

        job.canceled.connect(lambda: self.on_job_canceled(job))
        job.finished.connect(lambda: self.on_job_finished(job))
        job.progress_changed.connect(lambda _: self.updated.emit())

        self.current_jobs.append(job)
        self.job_started.emit(job)
        self.updated.emit()

        logging.info(f"{job.name} started in the background")

        return job

    def on_job_finished(self, job: BackgroundJob) -> None:
        logging.info(f"{job.name} finished")
        neon_player.instance().show_notification(
            "Job finished",
            f"Job '{job.name}' has completed"
        )
        self.remove_job(job)
        self.updated.emit()

    def on_job_canceled(self, job: BackgroundJob) -> None:
        self.job_canceled.emit(job)
        self.remove_job(job)
        self.updated.emit()

    def remove_job(self, job: BackgroundJob) -> None:
        self.job_counter -= 1
        self.current_jobs.remove(job)
        self.job_finished.emit(job)
