from typing import ClassVar

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPainter
from qt_property_widgets.utilities import PersistentPropertiesMixin

from pupil_labs import neon_player
from pupil_labs.neon_recording import NeonRecording


class Plugin(PersistentPropertiesMixin, QObject):
    changed = Signal()
    known_classes: ClassVar[list] = []

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
