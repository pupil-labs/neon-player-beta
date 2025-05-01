import contextlib
import multiprocessing as mp
import signal
import traceback

from PySide6.QtCore import QObject, QTimer, Signal


class ProgressUpdate:
    def __init__(self, progress, datum=None):
        self.progress = progress
        self.datum = datum


class BGWorkerQtHelper(QObject):
    finished = Signal()
    cancelled = Signal()
    progress_changed = Signal(float)

    def __init__(self, bg_worker):
        super().__init__()

        self.bg_worker = bg_worker

        self.poller = QTimer()
        self.poller.setInterval(10)
        self.poller.timeout.connect(self.bg_worker.fetch)

    def start(self):
        self.poller.start()

    def stop(self):
        self.poller.stop()


class BGWorker:
    """Future-like object. Iterates a generator in the background"""

    def __init__(self, name, generator, *args, **kwargs):
        super().__init__()
        self.qt_helper = BGWorkerQtHelper(self)

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
        self.progress = 0

    def __getstate__(self):
        state = self.__dict__.copy()
        if 'qt_helper' in state:
            del state['qt_helper']

        return state

    def start(self):
        self.qt_helper.start()
        self.process.start()

    def _wrapper(self, pipe, generator, *args, **kwargs):
        """Executed in background, pipes generator results to foreground

        All exceptions are caught, forwarded to the foreground, and raised in
        `Task_Proxy.fetch()`. This allows users to handle failure gracefully
        as well as raising their own exceptions in the background task.
        """  # noqa: D401

        def interrupt_handler(sig, frame):
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

    def fetch(self):
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

    def cancel(self, timeout=1):
        if not (self.completed or self.canceled):
            self._cancel_event.set()
            for _ in self.fetch():
                # fetch to flush pipe to allow process to react to cancel comand
                pass

        if self.process is not None:
            self.process.join(timeout)
            self.process = None
