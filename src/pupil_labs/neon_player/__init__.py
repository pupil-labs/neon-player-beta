import functools
import typing as T

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPainter
from qt_property_widgets.utilities import PersistentPropertiesMixin
from qt_property_widgets.utilities import action as object_action

from pupil_labs import neon_player
from pupil_labs.neon_player.job_manager import BGWorker, ProgressUpdate
from pupil_labs.neon_recording import NeonRecording


class Plugin(PersistentPropertiesMixin, QObject):
    changed = Signal()
    known_classes: T.ClassVar[list] = []

    def __init__(self) -> None:
        super().__init__()
        self.render_layer = 1
        self._enabled = False

        neon_player.instance().aboutToQuit.connect(self.on_disabled)

    @classmethod
    def __init_subclass__(cls: type["Plugin"], **kwargs: dict) -> None:  # type: ignore
        super().__init_subclass__(**kwargs)
        Plugin.known_classes.append(cls)

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        pass

    def render(self, painter: QPainter, time_in_recording: int) -> None:
        pass

    def on_disabled(self) -> None:
        pass


def instance():  # type: ignore
    from pupil_labs.neon_player.app import NeonPlayerApp

    return NeonPlayerApp.instance()


def action(func: T.Callable) -> T.Any:
    @functools.wraps(func)
    def wrapper(*args: T.Any, **kwargs: T.Any) -> T.Any:
        result = func(*args, **kwargs)
        if isinstance(result, BGWorker):
            app = instance()
            app.start_bg_worker(result)

        return result

    return object_action(wrapper)


__all__ = [
    "BGWorker",
    "Plugin",
    "ProgressUpdate",
    "action",
    "instance",
]
