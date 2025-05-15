import argparse
import importlib.util
import json
import logging
import logging.handlers
import multiprocessing as mp
import sys
import time
import typing
from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QAction, QColor, QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication,
)
from qt_property_widgets.utilities import ComplexEncoder

from pupil_labs import neon_recording as nr
from pupil_labs.neon_player import Plugin

from .job_manager import JobManager
from .settings import GeneralSettings
from .ui import MainWindow


def setup_logging() -> None:
    """Configure logging to both console and file."""
    log_dir = Path.home() / "Pupil Labs" / "Neon Player" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "neon_player.log"

    # Set up root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Create formatters
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    file_formatter = logging.Formatter(log_format)
    console_formatter = logging.Formatter(log_format)

    # File handler with rotation (10MB per file, keep 5 backups)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(file_formatter)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(console_formatter)

    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # Log startup message
    logging.info("Neon Player starting up")
    logging.info(f"Logging to file: {log_file}")


class NeonPlayerApp(QApplication):
    playback_state_changed = Signal(bool)
    position_changed = Signal(object)

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
        self.job_manager = JobManager()

        # Iterate through all modules within plugins and register them
        self.find_plugins(Path(__file__).parent / "plugins")

        try:
            self.settings: GeneralSettings = GeneralSettings.from_dict(
                self.load_settings()
            )
        except Exception:
            logging.exception("Failed to load settings")
            self.settings = GeneralSettings()

        parser = argparse.ArgumentParser()
        parser.add_argument("recording", nargs="?", default=None, help="")
        args = parser.parse_args()

        self.main_window = MainWindow()

        for plugin_class in Plugin.known_classes:
            enabled = plugin_class.__name__ in self.settings.enabled_plugin_names
            if enabled:
                state = self.settings.plugin_states.get(plugin_class.__name__, {})
                self.toggle_plugin(plugin_class, True, state)

        if args.recording:
            QTimer.singleShot(1, lambda: self.load(Path(args.recording)))

    def load_settings(self) -> typing.Any:
        settings_path = Path.home() / "Pupil Labs" / "Neon Player" / "settings.json"
        logging.info(f"Loading settings from {settings_path}")
        return json.loads(settings_path.read_text())

    def save_settings(self) -> None:
        settings_path = Path.home() / "Pupil Labs" / "Neon Player" / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        data = self.settings.to_dict()
        with settings_path.open("w") as f:
            json.dump(data, f, cls=ComplexEncoder)

    def find_plugins(self, path: Path) -> None:
        sys.path.append(str(path))
        logging.info(f"Searching for plugins in {path}")
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

                logging.info(f"Loading plugin {d}")

                module = importlib.util.module_from_spec(spec)
                sys.modules[d.stem] = module
                if spec.loader:
                    spec.loader.exec_module(module)

            except Exception:
                logging.exception(f"Failed to load plugin {d}")

    def toggle_plugin(
        self,
        kls: type[Plugin],
        enabled: bool,
        state: typing.Optional[dict] = None,
    ) -> typing.Optional[Plugin]:
        if enabled:
            logging.info(f"Enabling plugin {kls.__name__}")
            try:
                if state is None:
                    state = self.settings.plugin_states.get(kls.__name__, {})

                plugin: Plugin = kls.from_dict(state)

                self.plugins_by_class[kls] = plugin
                self.main_window.settings_panel.set_plugin_instance(kls, plugin)

                plugin.changed.connect(lambda: self.on_plugin_changed(plugin))

                if self.recording:
                    plugin.on_recording_loaded(self.recording)
            except Exception:
                logging.exception(f"Failed to enable plugin {kls}")
                return None

        else:
            logging.info(f"Disabling plugin {kls.__name__}")
            plugin = self.plugins_by_class[kls]

            plugin.on_disabled()
            del self.plugins_by_class[kls]
            self.main_window.settings_panel.set_plugin_instance(kls, None)

        try:
            self.save_settings()
        except Exception:
            logging.exception("Failed to save settings")

        self.plugins = list(self.plugins_by_class.values())
        self.plugins.sort(key=lambda p: p.render_layer)

        self.main_window.video_widget.update()

        return plugin

    def on_plugin_changed(self, plugin: Plugin) -> None:
        self.main_window.video_widget.update()
        self.save_settings()

    def run(self) -> int:
        self.main_window.show()
        return self.exec()

    def load(self, path: Path) -> None:
        """Load a recording from the given path."""
        logging.info("Opening recording at path: %s", path)
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

        self.position_changed.emit(self.current_ts)

    def seek_to(self, ts: int) -> None:
        if self.recording is None:
            return

        now = time.time_ns()
        self.current_ts = ts
        self.playback_start_anchor = now - (ts - self.recording.start_ts)
        self.main_window.set_time_in_recording(ts)

        self.position_changed.emit(self.current_ts)

    def render_to(self, painter: QPainter, ts: typing.Optional[int] = None) -> None:
        if ts is None:
            ts = self.current_ts

        for plugin in self.plugins:
            plugin.render(painter, ts)

    def export_all(self) -> None:
        for plugin in self.plugins:
            if hasattr(plugin, "run_export"):
                plugin.run_export()

    @property
    def is_playing(self) -> bool:
        return self.refresh_timer.isActive()


def main() -> None:
    mp.set_start_method("spawn")
    setup_logging()
    app = NeonPlayerApp(sys.argv)
    sys.exit(app.run())


if __name__ == "__main__":
    main()
