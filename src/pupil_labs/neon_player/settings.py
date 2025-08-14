from PySide6.QtCore import QObject, Signal
from qt_property_widgets.utilities import PersistentPropertiesMixin, property_params

from pupil_labs import neon_player
from pupil_labs.neon_player import Plugin


class GeneralSettings(PersistentPropertiesMixin, QObject):
    changed = Signal()
    def __init__(self) -> None:
        super().__init__()
        self._skip_gray_frames_on_load = True

        plugin_names = [k.get_label() for k in Plugin.known_classes]
        plugin_names.sort()
        self._default_plugins = dict.fromkeys(plugin_names, False)
        self._default_plugins.update({
            "GazeDataPlugin": True,
            "SceneRendererPlugin": True,
            "EventsPlugin": True,
        })

    @property
    def skip_gray_frames_on_load(self) -> bool:
        return self._skip_gray_frames_on_load

    @skip_gray_frames_on_load.setter
    def skip_gray_frames_on_load(self, value: bool) -> None:
        self._skip_gray_frames_on_load = value

    @property
    def default_plugins(self) -> dict[str, bool]:
        return self._default_plugins

    @default_plugins.setter
    def default_plugins(self, value: dict[str, bool]) -> None:
        self._default_plugins = value.copy()


class RecordingSettings(PersistentPropertiesMixin, QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._enabled_plugins = neon_player.instance().settings.default_plugins.copy()
        self._plugin_states: dict[str, dict] = {}

    @property
    def enabled_plugins(self) -> dict[str, bool]:
        return self._enabled_plugins

    @enabled_plugins.setter
    def enabled_plugins(self, value: dict[str, bool]) -> None:
        self._enabled_plugins = value.copy()

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

    def __setstate__(self, state: dict) -> None:
        super().__setstate__(state)
        for kls in Plugin.known_classes:
            if kls.__name__ not in state["enabled_plugins"]:
                self._enabled_plugins[kls.__name__] = False
