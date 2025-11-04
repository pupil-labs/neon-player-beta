import json
import typing as T
from pathlib import Path

from numpyencoder import NumpyEncoder
from pupil_labs.neon_recording import NeonRecording
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPainter
from qt_property_widgets.utilities import PersistentPropertiesMixin, property_params

from pupil_labs import neon_player
from pupil_labs.neon_player.ui import QtShortcutType
from pupil_labs.neon_player.ui.timeline_dock import TimeLineDock

if T.TYPE_CHECKING:
    from pupil_labs.neon_player.app import NeonPlayerApp


class GlobalPluginProperties(PersistentPropertiesMixin):
    _known_types: T.ClassVar[list[type["GlobalPluginProperties"]]] = []

    def __init_subclass__(cls) -> None:
        GlobalPluginProperties._known_types.append(cls)
        return super().__init_subclass__()

    def to_dict(self, include_class_name: bool = True) -> dict:
        return super().to_dict(include_class_name=include_class_name)


class Plugin(PersistentPropertiesMixin, QObject):
    changed = Signal()
    known_classes: T.ClassVar[list] = []
    global_properties: T.ClassVar[GlobalPluginProperties|None] = None

    def __init__(self) -> None:
        super().__init__()
        self.render_layer = 1
        self._enabled = False

        neon_player.instance().aboutToQuit.connect(self.on_disabled)

    def register_action(self, name: str, shortcut: QtShortcutType, func: T.Callable) -> None:
        return self.app.main_window.register_action(name, shortcut, func)

    def unregister_action(self, name: str) -> None:
        return self.app.main_window.unregister_action(name)

    def register_timeline_action(self, name: str, shortcut: QtShortcutType, func: T.Callable) -> None:
        return self.app.main_window.register_action(f"Timeline/{name}", shortcut, func)

    def unregister_timeline_action(self, name: str) -> None:
        return self.app.main_window.unregister_action(f"Timeline/{name}")

    def register_data_point_action(self, event_name: str, action_name: str, callback: T.Callable) -> None:
        self.app.main_window.timeline.register_data_point_action(
            event_name,
            action_name,
            callback
        )

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

    def trigger_scene_update(self) -> None:
        self.app.main_window.video_widget.update()

    def get_timeline(self) -> TimeLineDock:
        return self.app.main_window.timeline

    def get_cache_path(self) -> Path:
        if self.recording is None:
            return None

        cache_dir = self.recording._rec_dir / ".neon_player" / "cache"
        return cache_dir / self.__class__.__name__

    def load_cached_json(self, filename: str) -> T.Any:
        if self.recording is None:
            return None

        cache_file = self.get_cache_path() / filename

        if not cache_file.exists():
            return None

        with cache_file.open("r") as f:
            return json.load(f)

    def save_cached_json(self, filename: str, data: T.Any) -> None:
        if self.recording is None:
            return

        cache_file = self.get_cache_path() / filename
        cache_file.parent.mkdir(parents=True, exist_ok=True)

        with cache_file.open("w") as f:
            json.dump(data, f, cls=NumpyEncoder)

    def get_scene_idx_for_time(
        self,
        t: int = -1,
        method: T.Literal["nearest", "backward", "forward"] = "backward",
        tolerance: int | None = None
    ) -> int:
        return self.app.get_scene_idx_for_time(t, method, tolerance)

    def is_time_gray(self, t: int = -1) -> bool:
        if t == -1:
            t = self.app.current_ts

        gray_frame = t < self.recording.scene.time[0]
        if not gray_frame:
            scene_frame = self.recording.scene.sample([t], method="backward")[0]
            gray_frame = abs(t - scene_frame.time) / 1e9 > 1 / 15

        return gray_frame

    @property
    @property_params(widget=None, dont_encode=True)
    def recording(self) -> NeonRecording | None:
        return neon_player.instance().recording

    @property
    @property_params(widget=None, dont_encode=True)
    def app(self) -> "NeonPlayerApp":
        return neon_player.instance()

    @property
    @property_params(widget=None, dont_encode=True)
    def job_manager(self) -> "JobManager":
        return neon_player.instance().job_manager

    @staticmethod
    def get_class_by_name(name: str) -> type["Plugin"]:
        for cls in Plugin.known_classes:
            if cls.__name__ == name:
                return cls

        raise ValueError(f"Plugin class {name} not found")

    @staticmethod
    def get_instance_by_name(name: str) -> "Plugin":
        return neon_player.instance().plugins_by_class.get(name)

    @classmethod
    def get_label(cls: type["Plugin"]) -> str:
        if hasattr(cls, "label"):
            return cls.label

        return cls.__name__
