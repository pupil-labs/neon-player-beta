import inspect
import logging
import logging.handlers
import multiprocessing as mp
import multiprocessing.connection
import multiprocessing.synchronize
import traceback
import typing as T
from logging.handlers import QueueHandler, QueueListener

from PySide6.QtCore import QObject, QTimer, Signal

from pupil_labs import neon_player


class ProgressUpdate:
    def __init__(self, progress: float, datum: T.Any = None) -> None:
        self.progress = progress
        self.datum = datum


class EarlyCancellationError(Exception):
    pass


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


def setup_logging_queue() -> tuple[mp.Queue, QueueListener]:
    """Set up logging queue and listener in the main process.

    This creates a queue that forwards log records to the root logger,
    which will be handled by the console window's log handler.
    """
    log_queue: mp.Queue = mp.Queue()

    # Create a handler that forwards to the root logger
    class RootLoggerHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            logger = logging.getLogger()
            if logger.isEnabledFor(record.levelno):
                logger.handle(record)

    handler = RootLoggerHandler()
    handler.setLevel(logging.INFO)

    # Start the queue listener
    listener = QueueListener(log_queue, handler, respect_handler_level=True)
    listener.start()
    return log_queue, listener


class BGWorker:
    _job_counter = 0
    _log_queue = None
    _log_listener = None

    @classmethod
    def setup_logging(cls) -> None:
        """Set up logging queue and listener.

        Should be called once in the main process.
        """
        if cls._log_queue is None or cls._log_listener is None:
            cls._log_queue, cls._log_listener = setup_logging_queue()
            logging.info("Background process logging initialized")

    @classmethod
    def stop_logging(cls) -> None:
        """Stop the log listener. Should be called when the application is exiting."""
        if cls._log_listener is not None:
            cls._log_listener.stop()
            cls._log_listener = None
            cls._log_queue = None

    def __init__(
        self, name: str, generator: T.Callable, *args: T.Any, **kwargs: T.Any
    ) -> None:
        super().__init__()
        self.qt_helper = BGWorkerQtHelper(self)
        self.name = name
        BGWorker._job_counter += 1
        self.id = BGWorker._job_counter

        ctx = mp.get_context("spawn")

        self._was_completed = False
        self._was_canceled = False
        self._cancel_event = ctx.Event()

        pipe_recv, pipe_send = ctx.Pipe(False)
        wrapper_args = [pipe_send, self._cancel_event, BGWorker._log_queue, generator]
        wrapper_args.extend(args)
        self.process = ctx.Process(
            target=self._wrapper, name=name, args=wrapper_args, kwargs=kwargs
        )
        self.pipe = pipe_recv
        self.pipe_send = pipe_send
        self.progress = 0.0

        self.finished = self.qt_helper.finished
        self.canceled = self.qt_helper.canceled
        self.progress_changed = self.qt_helper.progress_changed

    def start(self) -> None:
        self.qt_helper.start()
        self.process.start()

    def __getstate__(self) -> T.Any:
        state = self.__dict__.copy()
        ignorables = ["qt_helper", "finished", "canceled", "progress_changed"]
        for ignorable in ignorables:
            del state[ignorable]

        return state

    def __str__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name}, id={self.id})"

    def _setup_child_logging(self, log_queue: mp.Queue) -> None:
        """Set up logging in the child process to send logs to the main process."""
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)

        # Clear existing handlers to avoid duplicate logs
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        # Add queue handler to send logs to the main process
        queue_handler = QueueHandler(log_queue)
        queue_handler.setLevel(logging.INFO)
        formatter = logging.Formatter(f"%(message)s [Job {self.id}]")
        queue_handler.setFormatter(formatter)
        root_logger.addHandler(queue_handler)
        # Ensure the root logger propagates to the queue handler
        root_logger.propagate = False

    def _wrapper(
        self,
        pipe: mp.connection.Connection,
        cancel_event: mp.synchronize.Event,
        log_queue: T.Optional[mp.Queue],
        func: T.Callable,
        *args: T.Any,
        **kwargs: T.Any,
    ) -> None:
        """Wrap generator in bg and pipe results to the main process

        All exceptions are caught, forwarded to the foreground, and raised in
        `Task_Proxy.fetch()`. This allows users to handle failure gracefully
        as well as raising their own exceptions in the background task.
        """
        try:
            # Set up logging in the child process if log queue is provided
            if log_queue is not None:
                self._setup_child_logging(log_queue)

            if inspect.isgeneratorfunction(func):
                for datum in func(*args, **kwargs):
                    if cancel_event.is_set():
                        raise EarlyCancellationError("Task was cancelled")  # noqa: TRY301

                    pipe.send(datum)

                pipe.send(StopIteration())
            else:
                result = func(*args, **kwargs)
                pipe.send(result)
                pipe.send(StopIteration())

        except BrokenPipeError:
            pass

        except EarlyCancellationError as exc:
            pipe.send(exc)

        except Exception as exc:
            pipe.send(traceback.TracebackException.from_exception(exc))

        finally:
            pipe.close()

    def fetch(self) -> None:
        if self._was_completed or self._was_canceled:
            return

        while self.pipe.poll(0):
            datum = self.pipe.recv()

            if isinstance(datum, StopIteration):
                self._was_completed = True
                self.qt_helper.finished.emit()
                return

            if isinstance(datum, EarlyCancellationError):
                self.qt_helper.canceled.emit()

            elif isinstance(datum, traceback.TracebackException):
                logging.error(
                    f"Job error [{self}]: {datum} - " + "".join(datum.format())
                )

            elif isinstance(datum, ProgressUpdate):
                self.progress = datum.progress
                self.qt_helper.progress_changed.emit(datum.progress)

    def cancel(self, timeout: float = 1) -> None:
        if not (self.was_completed or self.was_canceled):
            self._cancel_event.set()
            self.fetch()  # flush

        if self.process is not None:
            self.process.join(timeout)

    @property
    def was_completed(self) -> bool:
        return self._was_completed

    @property
    def was_canceled(self) -> bool:
        return self._was_canceled


class JobManager(QObject):
    progress_changed = Signal(float)
    job_started = Signal(BGWorker)
    job_finished = Signal(BGWorker)
    job_canceled = Signal(BGWorker)

    def __init__(self) -> None:
        super().__init__()

        self.bg_workers: list[BGWorker] = []
        self.job_count = 0

        app = neon_player.instance()
        app.aboutToQuit.connect(self.cleanup)

    def cleanup(self) -> None:
        BGWorker.stop_logging()
        for worker in self.bg_workers[:]:
            worker.cancel()

        for worker in self.bg_workers[:]:
            if worker.process is not None:
                worker.process.join(timeout=1.0)

        self.bg_workers.clear()

    def create_job(
        self, name: str, generator: T.Callable, *args: T.Any, **kwargs: T.Any
    ) -> BGWorker:
        worker = BGWorker(name, generator, *args, **kwargs)
        logging.info(f"Job created [{worker.id}] {worker.name}")
        self.add_job(worker)
        worker.start()
        self.job_started.emit(worker)
        return worker

    def add_job(self, bg_worker: BGWorker) -> None:
        self.bg_workers.append(bg_worker)
        self.job_count += 1

        bg_worker.qt_helper.progress_changed.connect(lambda _: self.update_progress())
        bg_worker.qt_helper.finished.connect(lambda: self.on_job_finished(bg_worker))
        bg_worker.qt_helper.canceled.connect(
            lambda: self.on_job_finished(bg_worker, True)
        )

    def on_job_finished(self, bg_worker: BGWorker, canceled: bool = False) -> None:
        self.bg_workers.remove(bg_worker)
        self.job_count -= 1
        self.update_progress()

        if canceled:
            logging.warning(f"Job canceled [{bg_worker.id}] {bg_worker.name}")
            self.job_canceled.emit(bg_worker)
        else:
            logging.info(f"Job finished [{bg_worker.id}] {bg_worker.name}")
            self.job_finished.emit(bg_worker)

    def update_progress(self) -> None:
        if self.job_count == 0:
            self.progress_changed.emit(1)
            return

        completed_job_count = self.job_count - len(self.bg_workers)
        progress = (
            completed_job_count + sum([worker.progress for worker in self.bg_workers])
        ) / self.job_count

        self.progress_changed.emit(progress)
