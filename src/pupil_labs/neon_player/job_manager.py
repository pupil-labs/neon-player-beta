import contextlib
import multiprocessing as mp
import multiprocessing.connection
import signal
import traceback
import types
import typing as T

from PySide6.QtCore import QObject, QTimer, Signal


class ProgressUpdate:
    def __init__(self, progress: float, datum : T.Any = None) -> None:
        self.progress = progress
        self.datum = datum


class BGWorkerQtHelper(QObject):
    finished = Signal()
    canceled = Signal()
    progress_changed = Signal(float)

    def __init__(self, bg_worker: "BGWorker") -> None:
        super().__init__()

        self.bg_worker = bg_worker

        self.poller = QTimer()
        self.poller.setInterval(10)
        self.poller.timeout.connect(self.bg_worker.fetch)

    def start(self) -> None:
        self.poller.start()

    def stop(self) -> None:
        self.poller.stop()


class BGWorker:
    """Future-like object. Iterates a generator in the background"""

    def __init__(self, name: str, generator: T.Callable, *args: T.Any, **kwargs: T.Any) -> None:
        super().__init__()
        self.qt_helper = BGWorkerQtHelper(self)
        self.name = name

        ctx = mp.get_context('spawn')

        self._completed = False
        self._canceled = False

        pipe_recv, pipe_send = ctx.Pipe(False)
        wrapper_args = [
            pipe_send, generator
        ]
        wrapper_args.extend(args)
        self.process = ctx.Process(
            target=self._wrapper, name=name, args=wrapper_args, kwargs=kwargs
        )
        self.pipe = pipe_recv
        self.pipe_send = pipe_send
        self.progress = 0.0

    def __getstate__(self) -> T.Any:
        state = self.__dict__.copy()
        if 'qt_helper' in state:
            del state['qt_helper']

        return state

    def start(self) -> None:
        self.qt_helper.start()
        self.process.start()

    def _wrapper(self, pipe: mp.connection.Connection, generator: T.Callable[..., T.Generator], *args: T.Any, **kwargs: T.Any) -> None:
        """Wrap generator in bg and pipe results to the main process

        All exceptions are caught, forwarded to the foreground, and raised in
        `Task_Proxy.fetch()`. This allows users to handle failure gracefully
        as well as raising their own exceptions in the background task.
        """

        def interrupt_handler(sig: int, frame: T.Optional[types.FrameType]) -> None:
            trace = traceback.format_stack(f=frame)
            print(f"Caught signal {sig} in:\n" + "".join(trace))

        signal.signal(signal.SIGINT, interrupt_handler)
        try:
            for datum in generator(*args, **kwargs):
                pipe.send(datum)

            pipe.send(StopIteration())

        except BrokenPipeError:
            pass

        except Exception as e:
            with contextlib.suppress(BrokenPipeError):
                pipe.send(e)

            print(traceback.format_exc())

        finally:
            pipe.close()

    def fetch(self) -> None:
        if self._completed or self._canceled:
            return

        while self.pipe.poll(0):
            try:
                datum = self.pipe.recv()
            except EOFError:
                print("Process canceled be user.")
                self._canceled = True
                self.qt_helper.canceled.emit()
                return

            else:
                if isinstance(datum, StopIteration):
                    self._completed = True
                    self.qt_helper.finished.emit()
                    return

                elif isinstance(datum, Exception):
                    raise datum

                elif isinstance(datum, ProgressUpdate):
                    self.progress = datum.progress
                    self.qt_helper.progress_changed.emit(datum.progress)

    # def cancel(self, timeout:  float = 1) -> None:
    #     if not (self.completed or self.canceled):
    #         self._cancel_event.set()
    #         self.fetch() # flush

    #     if self.process is not None:
    #         self.process.join(timeout)


class JobManager(QObject):
    progress_changed = Signal(float)
    job_started = Signal(BGWorker)
    job_finished = Signal(BGWorker)

    def __init__(self) -> None:
        super().__init__()

        self.bg_workers: list[BGWorker] = []
        self.job_count = 0

    def create_job(self, name: str, generator: T.Callable, *args: T.Any, **kwargs: T.Any) -> BGWorker:
        worker = BGWorker(name, generator, *args, **kwargs)
        self.add_job(worker)
        worker.start()
        self.job_started.emit(worker)
        return worker

    def add_job(self, bg_worker: BGWorker) -> None:
        self.bg_workers.append(bg_worker)
        self.job_count += 1

        bg_worker.qt_helper.progress_changed.connect(lambda _: self.update_progress())
        bg_worker.qt_helper.finished.connect(lambda: self.on_job_finished(bg_worker))

    def on_job_finished(self, bg_worker: BGWorker) -> None:
        self.bg_workers.remove(bg_worker)
        self.job_count -= 1
        self.update_progress()
        self.job_finished.emit(bg_worker)

    def update_progress(self) -> None:
        if self.job_count == 0:
            self.progress_changed.emit(1)
            return

        completed_job_count = self.job_count - len(self.bg_workers)
        progress = (completed_job_count + sum(
            [worker.progress for worker in self.bg_workers]
        )) / self.job_count

        self.progress_changed.emit(progress)
