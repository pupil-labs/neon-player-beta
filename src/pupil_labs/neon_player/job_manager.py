import logging
import os
import pickle
import subprocess
import sys
import typing as T
from dataclasses import dataclass
from pathlib import Path
from selectors import select

from PySide6.QtCore import QObject, QTimer, Signal
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
        *args: T.Any
    ):
        super().__init__()

        self.name = name
        self.job_id = job_id

        read_fd, write_fd = os.pipe()
        self.read_fd = read_fd

        os.set_inheritable(write_fd, True)

        args = [
            str(recording_path),
            "--progress_stream_fd",
            str(write_fd),
            "--job",
            action_name,
        ] + [str(arg) for arg in args]

        if neon_player.is_frozen():
            cmd = [sys.executable] + args
        else:
            cmd = [sys.executable, "-m", "pupil_labs.neon_player"] + args

        self.proc = subprocess.Popen(
            cmd,
            pass_fds=(write_fd,),
            close_fds=False  # keep our read_fd open
        )
        # Close our copy of the write end; child has its own copy
        os.close(write_fd)

        self.read_stream = os.fdopen(self.read_fd, 'rb', closefd=True)

        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self.poll)
        self.poll_timer.start(10)

    def poll(self):
        for obj in self.read_objects():
            if obj is None:
                return

            self.progress_changed.emit(obj.progress)
        else:
            self.poll_timer.stop()
            self.finished.emit()

    def read_objects(self):
        """Generator: poll the pipe and yield objects as they arrive."""
        with os.fdopen(self.read_fd, 'rb', closefd=False) as stream:
            while self.proc.returncode is None:
                # Wait until read_fd is ready or timeout expires
                rlist, _, _ = select.select([stream], [], [], 0)
                if not rlist:
                    # No data ready, yield control to caller
                    yield None
                    break

                # Read 4-byte length header
                length_bytes = stream.read(4)
                if not length_bytes:
                    break  # EOF
                length = int.from_bytes(length_bytes, byteorder='little')

                # Read the pickled payload
                data_bytes = stream.read(length)
                yield pickle.loads(data_bytes)

                if stream.closed:
                    return

    def cancel(self):
        self.proc.terminate()
        self.proc.wait()
        self.poll_timer.stop()


class JobManager(QObject):
    job_started = Signal(BackgroundJob)
    job_finished = Signal(BackgroundJob)
    job_canceled = Signal(BackgroundJob)

    def __init__(self):
        super().__init__()
        self.current_jobs = []
        self.job_counter = 0

    def work_job(self, job: T.Generator[ProgressUpdate, None, None]) -> None:
        progress_stream_fd = neon_player.instance().progress_stream_fd
        # runs in child process
        if progress_stream_fd:
            with open(progress_stream_fd, "wb") as progress_stream:
                for update in job:
                    data = pickle.dumps(update)
                    length = len(data).to_bytes(4, byteorder='little')
                    progress_stream.write(length + data)
        else:
            with tqdm(total=1.0) as pbar:
                for update in job:
                    pbar.n = update.progress
                    pbar.refresh()

    def run_background_action(self, name: str, action_name: str, *args: T.Any) -> BackgroundJob:
        if neon_player.instance().headless:
            logging.warning("Not starting background job in headless mode")
            return

        job = BackgroundJob(
            name,
            self.job_counter,
            neon_player.instance().recording._rec_dir,
            action_name,
            *args
        )
        self.job_counter += 1

        job.canceled.connect(lambda: self.on_job_canceled(job))
        job.finished.connect(lambda: self.remove_job(job))

        self.current_jobs.append(job)
        self.job_started.emit(job)

        return job

    def on_job_canceled(self, job: BackgroundJob) -> None:
        self.job_canceled.emit(job)
        self.remove_job(job)

    def remove_job(self, job: BackgroundJob) -> None:
        self.job_counter -= 1
        self.current_jobs.remove(job)
        self.job_finished.emit(job)
