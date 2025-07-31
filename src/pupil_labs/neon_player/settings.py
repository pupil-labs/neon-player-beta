from PySide6.QtCore import QObject, Qt, Signal
from qt_property_widgets.utilities import PersistentPropertiesMixin, property_params

from pupil_labs import neon_player

class GeneralSettings(PersistentPropertiesMixin, QObject):
    changed = Signal()
    def __init__(self) -> None:
        super().__init__()
        self._skip_gray_frames_on_load = True

    @property
    def skip_gray_frames_on_load(self) -> bool:
        return self._skip_gray_frames_on_load

    @skip_gray_frames_on_load.setter
    def skip_gray_frames_on_load(self, value: bool) -> None:
        self._skip_gray_frames_on_load = value


class RecordingSettings(PersistentPropertiesMixin, QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._enabled_plugin_names = [
            "GazeDataPlugin",
            "SceneRendererPlugin",
        ]
        self._plugin_states: dict[str, dict] = {}

    @property
    @property_params(widget=None)
    def enabled_plugin_names(self) -> list[str]:
        app = neon_player.instance()
        if app.applicationState() == Qt.ApplicationState.ApplicationActive:
            return list(app.plugins_by_class.keys())

        return self._enabled_plugin_names

    @enabled_plugin_names.setter
    def enabled_plugin_names(self, value: list[str]) -> None:
        self._enabled_plugin_names = value.copy()

    @property
    @property_params(widget=None)
    def plugin_states(self) -> dict[str, dict]:
        app = neon_player.instance()
        current_states = {
            class_name: p.to_dict() for class_name, p in app.plugins_by_class.items()
        }

        plugin_states = {**self._plugin_states, **current_states}

        self._plugin_states = {k: v for k, v in plugin_states.items() if v}

        return self._plugin_states

    @plugin_states.setter
    def plugin_states(self, value: dict[str, dict]) -> None:
        self._plugin_states = value.copy()
