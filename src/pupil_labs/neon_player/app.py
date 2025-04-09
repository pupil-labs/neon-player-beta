import importlib.util
import json
import sys
import time
import typing
from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QAction, QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
)
from qt_property_widgets.utilities import ComplexEncoder

from pupil_labs import neon_recording as nr
from pupil_labs.neon_player import Plugin

from .settings import GeneralSettings
from .ui import MainWindow


class NeonPlayerApp(QApplication):
    playback_state_changed = Signal(bool)

    def __init__(self, argv: list[str]) -> None:
        super().__init__(argv)

        self.setPalette(QPalette(QColor("#1d2023")))

        self.plugins_by_class: dict[type, Plugin] = {}
        self.plugins: list[Plugin] = []
        self.recording: typing.Optional[nr.NeonRecording] = None
        self.playback_start_anchor = 0
        self.current_ts = 0

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(0)
        self.refresh_timer.timeout.connect(self.poll)

        # Iterate through all modules within plugins and register them
        self.find_plugins(Path(__file__).parent / "plugins")

        try:
            self.settings: GeneralSettings = GeneralSettings.from_dict(
                self.load_settings()
            )
        except Exception as exc:
            print("Failed to load settings", exc)
            self.settings = GeneralSettings()

        for plugin_class in Plugin.known_classes:
            enabled = plugin_class.__name__ in self.settings.enabled_plugin_names
            if enabled:
                state = self.settings.plugin_states.get(plugin_class.__name__, {})
                QTimer.singleShot(
                    1, lambda p=plugin_class, s=state: self.toggle_plugin(p, True, s)
                )

        self.main_window = MainWindow()
        self.settings.changed.connect(self.save_settings)

        if len(argv) > 1:
            QTimer.singleShot(1, lambda: self.load(Path(argv[1])))

    def load_settings(self) -> typing.Any:
        settings_path = Path.home() / "Pupil Labs" / "Neon Player" / "settings.json"
        return json.loads(settings_path.read_text())

    def save_settings(self) -> None:
        settings_path = Path.home() / "Pupil Labs" / "Neon Player" / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        data = self.settings.to_dict()
        with settings_path.open("w") as f:
            json.dump(data, f, cls=ComplexEncoder)

    def find_plugins(self, path: Path) -> None:
        for d in path.iterdir():
            if d.is_file() and d.suffix != ".py":
                continue

            if d.name == "__pycache__":
                continue

            try:
                if d.is_dir():
                    spec = importlib.util.spec_from_file_location(
                        d.stem, d / "__init__.py"
                    )
                else:
                    spec = importlib.util.spec_from_file_location(d.stem, d)

                if spec is None:
                    continue

                module = importlib.util.module_from_spec(spec)
                sys.modules[d.stem] = module
                if spec.loader:
                    spec.loader.exec_module(module)

            except Exception as exc:
                print("Failed to load plugin", d, exc)

    def toggle_plugin(
        self, kls: type[Plugin], enabled: bool, state: typing.Optional[dict]
    ) -> typing.Optional[Plugin]:
        if enabled:
            if state is None:
                state = self.settings.plugin_states.get(kls.__name__, {})

            plugin: Plugin = kls.from_dict(state)

            self.plugins_by_class[kls] = plugin
            self.main_window.settings_panel.set_plugin_instance(kls, plugin)

            plugin.changed.connect(lambda: self.on_plugin_changed(plugin))

            if self.recording:
                plugin.on_recording_loaded(self.recording)
        else:
            plugin = self.plugins_by_class[kls]

            plugin.on_disabled()
            del self.plugins_by_class[kls]
            self.main_window.settings_panel.set_plugin_instance(kls, None)

        try:
            self.save_settings()
        except Exception as exc:
            print("Failed to save settings", exc)

        self.plugins = list(self.plugins_by_class.values())
        self.plugins.sort(key=lambda p: p.render_layer)

        self.main_window.video_widget.update()

        return plugin

    def on_plugin_changed(self, plugin: Plugin) -> None:
        self.main_window.video_widget.update()
        self.save_settings()

    def run(self) -> None:
        self.main_window.show()
        sys.exit(self.exec())

    def load(self, path: Path) -> None:
        print("Opening recording at path:", path)
        self.recording = nr.load(path)
        self.playback_start_anchor = 0

        self.main_window.on_recording_loaded(self.recording)
        for plugin in self.plugins:
            plugin.on_recording_loaded(self.recording)

        if self.settings.skip_gray_frames_on_load:
            self.seek_to(self.recording.scene[0].ts)
        else:
            self.seek_to(self.recording.start_ts)

    def get_action(self, action_path: str) -> typing.Optional[QAction]:
        return self.main_window.get_action(action_path)

    def toggle_play(self) -> None:
        if self.recording is None:
            return

        now = time.time_ns()
        if self.current_ts >= self.recording.stop_ts:
            self.current_ts = self.recording.start_ts

        if self.refresh_timer.isActive():
            self.refresh_timer.stop()

        else:
            elapsed_time = self.current_ts - self.recording.start_ts
            self.playback_start_anchor = now - elapsed_time
            self.refresh_timer.start()

        self.playback_state_changed.emit(self.refresh_timer.isActive())

    def poll(self) -> None:
        if self.recording is None:
            return

        now = time.time_ns()
        elapsed_time = now - self.playback_start_anchor
        target_ts = elapsed_time + self.recording.start_ts

        if self.current_ts < self.recording.stop_ts:
            self.current_ts = target_ts
            self.main_window.set_time_in_recording(self.current_ts)

        else:
            self.current_ts = self.recording.stop_ts
            self.main_window.set_time_in_recording(self.current_ts)

            self.refresh_timer.stop()
            self.playback_state_changed.emit(self.refresh_timer.isActive())

    def seek_to(self, ts: int) -> None:
        if self.recording is None:
            return

        now = time.time_ns()
        self.current_ts = ts
        self.playback_start_anchor = now - (ts - self.recording.start_ts)
        self.main_window.set_time_in_recording(ts)

    @property
    def is_playing(self) -> bool:
        return self.refresh_timer.isActive()


def main() -> None:
    app = NeonPlayerApp(sys.argv)
    app.run()


if __name__ == "__main__":
    main()
