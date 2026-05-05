import json
import logging

from pathlib import Path
from PySide6.QtCore import QObject, Signal
from qt_property_widgets.utilities import (
    PersistentPropertiesMixin, property_params, ComplexEncoder
)

from pupil_labs import neon_player
from pupil_labs.neon_player import GlobalPluginProperties, Plugin
from pupil_labs.neon_recording import NeonRecording


def plugin_label_lookup(cls_name: str) -> str:
    try:
        cls = Plugin.get_class_by_name(cls_name)
        if cls and hasattr(cls, "label"):
            return cls.label
        else:
            return cls_name
    except ValueError:
        pass

    return f"{cls_name} (missing?)"


class GeneralSettings(PersistentPropertiesMixin, QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._skip_gray_frames_on_load = True
        self._show_fps = False

        plugin_names = [k.__name__ for k in Plugin.known_classes]
        plugin_names.sort()
        self._default_plugins = dict.fromkeys(plugin_names, False)
        self._default_plugins.update({
            "GazeDataPlugin": True,
            "AudioPlugin": True,
            "SceneRendererPlugin": True,
            "EventsPlugin": True,
            "ExportAllPlugin": True,
        })

    @property
    def skip_gray_frames_on_load(self) -> bool:
        return self._skip_gray_frames_on_load

    @skip_gray_frames_on_load.setter
    def skip_gray_frames_on_load(self, value: bool) -> None:
        self._skip_gray_frames_on_load = value

    @property
    def show_fps(self) -> bool:
        return self._show_fps

    @show_fps.setter
    def show_fps(self, value: bool) -> None:
        self._show_fps = value

    @property
    def default_plugins(self) -> dict[str, bool]:
        for cls in Plugin.known_classes:
            if cls.__name__ not in self._default_plugins:
                self._default_plugins[cls.__name__] = False

        return self._default_plugins

    @default_plugins.setter
    def default_plugins(self, value: dict[str, bool]) -> None:
        self._default_plugins = value.copy()

    @property
    @property_params(widget=None)
    def plugin_globals(self) -> dict[str, GlobalPluginProperties]:
        value = {}
        for cls in Plugin.known_classes:
            if cls.global_properties is not None:
                value[cls.__name__] = cls.global_properties

        return value

    @plugin_globals.setter
    def plugin_globals(self, value: dict[str, GlobalPluginProperties]) -> None:
        for k, v in value.items():
            for cls in Plugin.known_classes:
                if k == cls.__name__:
                    cls.global_properties = v


class RecordingSettings(PersistentPropertiesMixin, QObject):
    changed = Signal()
    export_window_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._enabled_plugins = neon_player.instance().settings.default_plugins.copy()
        self._plugin_states: dict[str, dict] = {}
        self._export_window: list[int] = []

    @property
    @property_params(widget=None)
    def export_window(self) -> list[int]:
        return self._export_window

    @export_window.setter
    def export_window(self, value: list[int]) -> None:
        self._export_window = value.copy()
        self.export_window_changed.emit()
        self.changed.emit()

    @property
    @property_params(label_lookup=plugin_label_lookup)
    def enabled_plugins(self) -> dict[str, bool]:
        for cls in Plugin.known_classes:
            if cls.__name__ not in self._enabled_plugins:
                self._enabled_plugins[cls.__name__] = False

        return self._enabled_plugins

    @enabled_plugins.setter
    def enabled_plugins(self, value: dict[str, bool]) -> None:
        self._enabled_plugins = value.copy()

    @property
    @property_params(widget=None)
    def plugin_states(self) -> dict[str, dict]:
        app = neon_player.instance()
        # XXX: double-check
        if app.plugin_settings.recording_settings == self:
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


class PluginSettingsDispatcher(QObject):
    changed = Signal()
    export_window_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.recording_settings = RecordingSettings()
        self.workspace_settings = RecordingSettings()
        self.batch_mode_enabled = False
        self.default_source = self.recording_settings

    def load_recording_settings(self, settings_path: Path, recording: NeonRecording) -> None:
        try:
            if settings_path.exists():
                logging.info(f"Loading recording settings from {settings_path}")
                self.recording_settings = RecordingSettings.from_dict(
                    json.loads(settings_path.read_text())
                )

                if len(self.recording_settings.export_window) != 2:
                    logging.warning("Invalid export window in settings")
                    self.recording_settings.export_window = [
                        recording.start_time,
                        recording.stop_time,
                    ]

            else:
                self.recording_settings = RecordingSettings()
                self.recording_settings.export_window = [
                    recording.start_time,
                    recording.stop_time,
                ]

        except Exception:
            logging.exception("Failed to load settings")
            self.recording_settings = RecordingSettings()

        logging.info(
            "Recording settings loaded", self.recording_settings.enabled_plugins
        )

    def save_recording_settings(self, settings_path: Path) -> None:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        data = self.recording_settings.to_dict()
        with settings_path.open("w") as f:
            json.dump(data, f, cls=ComplexEncoder)

    def set_batch_mode(self, batch_mode_enabled: bool) -> None:
        self.batch_mode_enabled = batch_mode_enabled
        self.default_source = (
            self.recording_settings
            if not batch_mode_enabled else self.workspace_settings
        )

    @property
    def export_window(self) -> list[int]:
        return self.recording_settings.export_window

    @export_window.setter
    def export_window(self, value: list[int]) -> None:
        self.recording_settings.export_window = value
        self.export_window_changed.emit()

    @property
    @property_params(label_lookup=plugin_label_lookup)
    def enabled_plugins(self) -> dict[str, bool]:
        return self.default_source.enabled_plugins

    @enabled_plugins.setter
    def enabled_plugins(self, value: dict[str, bool]) -> None:
        self.default_source.enabled_plugins = value

    @property
    def plugin_states(self) -> dict[str, dict]:
        if not self.batch_mode_enabled:
            return self.recording_settings.plugin_states

        # TODO: merge workspace and recording settings

    @plugin_states.setter
    def plugin_states(self, value: dict[str, dict]) -> None:
        pass
