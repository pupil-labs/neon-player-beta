import typing as T

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPainter
from qt_property_widgets.utilities import PersistentPropertiesMixin, property_params

from pupil_labs import neon_player
from pupil_labs.neon_recording import NeonRecording

if T.TYPE_CHECKING:
    from pupil_labs.neon_player.app import NeonPlayerApp


class Plugin(PersistentPropertiesMixin, QObject):
    changed = Signal()
    known_classes: T.ClassVar[list] = []

    def __init__(self) -> None:
        super().__init__()
        self.render_layer = 1
        self._enabled = False

        neon_player.instance().aboutToQuit.connect(self.on_disabled)

    def add_dynamic_action(self, name: str, func: T.Callable) -> None:
        my_prop_form = self.app.main_window.settings_panel.plugin_class_expanders[self.__class__.__name__].content_widget
        my_prop_form.add_action(name, func)

    @classmethod
    def __init_subclass__(cls: type["Plugin"], **kwargs: dict) -> None:  # type: ignore
        super().__init_subclass__(**kwargs)
        if cls.__name__ not in [c.__name__ for c in Plugin.known_classes]:
            Plugin.known_classes.append(cls)

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        pass

    def render(self, painter: QPainter, time_in_recording: int) -> None:
        pass

    def on_disabled(self) -> None:
        pass

    @property
    @property_params(widget=None, dont_encode=True)
    def recording(self) -> NeonRecording | None:
        return neon_player.instance().recording

    @property
    @property_params(widget=None, dont_encode=True)
    def app(self) -> "NeonPlayerApp":
        return neon_player.instance()
