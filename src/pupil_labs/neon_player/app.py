import argparse
import importlib.util
import json
import logging
import logging.handlers
import sys
import time
import typing
from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QSystemTrayIcon,
)
from qt_property_widgets.utilities import ComplexEncoder, create_action_object

from pupil_labs import neon_player
from pupil_labs import neon_recording as nr
from pupil_labs.neon_player import Plugin
from pupil_labs.neon_player.job_manager import JobManager
from pupil_labs.neon_player.plugins import (
    audio,  # noqa: F401
    events,  # noqa: F401
    eye_overlay,  # noqa: F401
    eyestate,  # noqa: F401
    fixations,  # noqa: F401
    gaze,  # noqa: F401
    imu,  # noqa: F401
    scene_renderer,  # noqa: F401
    video_exporter,  # noqa: F401
)
from pupil_labs.neon_player.settings import GeneralSettings, RecordingSettings
from pupil_labs.neon_player.ui.main_window import MainWindow
from pupil_labs.neon_player.utilities import clone_menu


def setup_logging() -> None:
    """Configure logging to both console and file."""
    log_dir = Path.home() / "Pupil Labs" / "Neon Player" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "neon_player.log"

    # Set up root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Create formatters
    log_formatter = logging.Formatter(neon_player.LOG_FORMAT_STRING)

    # File handler with rotation (10MB per file, keep 5 backups)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(log_formatter)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)

    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # Log startup message
    logging.info("Neon Player starting up")
    logging.info(f"Logging to file: {log_file}")

class NeonPlayerApp(QApplication):
    playback_state_changed = Signal(bool)
    position_changed = Signal(object)
    seeked = Signal(object)
    speed_changed = Signal(float)
    recording_loaded = Signal(object)
    recording_unloaded = Signal()

    def __init__(self, argv: list[str]) -> None:
        self._initializing = True
        super().__init__(argv)

        self.setApplicationName("Neon Player")
        self.setWindowIcon(QIcon(str(neon_player.asset_path("neon-player.svg"))))
        self.setStyle("Fusion")

        self.tray_icon = QSystemTrayIcon()
        self.tray_icon.setIcon(self.windowIcon())
        self.tray_icon.setToolTip("Neon Player")

        self.plugins_by_class: dict[str, Plugin] = {}
        self.plugins: list[Plugin] = []
        self.recording: nr.NeonRecording | None = None
        self.playback_start_anchor = 0
        self.current_ts = 0
        self.playback_speed = 1.0

        self.settings = GeneralSettings()
        self.recording_settings = None

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(0)
        self.refresh_timer.timeout.connect(self.poll)
        self.job_manager = JobManager()

        parser = argparse.ArgumentParser()
        parser.add_argument("recording", nargs="?", default=None, help="")
        parser.add_argument("--progress_stream_fd", type=int, default=None)
        parser.add_argument(
            "--plugin-action",
            action="append",
            nargs="+",
            default=[],
            help="Run a named action with arguments",
        )
        parser.add_argument(
            "--job",
            nargs="+",
            default=None,
        )

        self.args = parser.parse_args()

        self.progress_stream_fd = self.args.progress_stream_fd

        self.main_window = MainWindow()

        setup_logging()

        # Iterate through all modules within plugins and register them
        plugin_search_path = Path.home() / "Pupil Labs" / "Neon Player" / "plugins"
        if plugin_search_path.exists():
            self.find_plugins(plugin_search_path)

        try:
            self.settings = GeneralSettings.from_dict(self.load_global_settings())
        except FileNotFoundError:
            logging.warning("Settings file not found")
        except Exception:
            logging.exception("Failed to load settings")

        if self.args.recording:
            QTimer.singleShot(1, lambda: self.load(Path(self.args.recording)))

        self._initializing = False

        if self.args.plugin_action:
            QTimer.singleShot(100, lambda: self.run_plugin_actions(self.args.plugin_action))

        if self.args.job:
            QTimer.singleShot(100, lambda: self.run_jobs(self.args.job))

    def run_jobs(self, job):
        plugin_name, action_name = job[0].split(".")
        job_args = job[1:]

        for plugin in self.plugins:
            if plugin.__class__.__name__ == plugin_name:
                # use an action object to provide type conversion for arguments
                if action_name not in plugin._action_objects:
                    action_obj = create_action_object(
                        getattr(plugin, action_name),
                        plugin
                    )
                else:
                    action_obj = plugin._action_objects[action_name]

                keys = list(action_obj.args.keys())
                if len(keys) > 0 and keys[0] == "self":
                    keys = keys[1:]

                args = dict(zip(keys, job_args))
                action_obj.__setstate__(args)
                self.job_manager.work_job(action_obj())

                break
        else:
            logging.error(f"Could not find plugin action method: {job[0]}")

        self.quit()

    def load_global_settings(self) -> typing.Any:
        settings_path = Path.home() / "Pupil Labs" / "Neon Player" / "settings.json"
        logging.info(f"Loading settings from {settings_path}")
        return json.loads(settings_path.read_text())

    def save_settings(self) -> None:
        if self._initializing:
            return

        if not hasattr(self, "_save_timer"):
            self._save_timer = QTimer(self)
            self._save_timer.setSingleShot(True)
            self._save_timer.timeout.connect(self._save_settings)
            self._save_timer.setInterval(2000)

        self._save_timer.start()

    def _save_settings(self) -> None:
        logging.info("Saving settings")
        try:
            settings_path = Path.home() / "Pupil Labs" / "Neon Player" / "settings.json"
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            data = self.settings.to_dict()
            with settings_path.open("w") as f:
                json.dump(data, f, cls=ComplexEncoder)

            if self.recording:
                settings_path = self.recording._rec_dir / ".neon_player" / "settings.json"
                settings_path.parent.mkdir(parents=True, exist_ok=True)
                data = self.recording_settings.to_dict()
                with settings_path.open("w") as f:
                    json.dump(data, f, cls=ComplexEncoder)

        except Exception:
            logging.exception("Failed to save settings")
            raise

    def find_plugins(self, path: Path) -> None:
        sys.path.append(str(path))
        sys.path.append(str(path / "site-packages"))
        logging.info(f"Searching for plugins in {path}")
        for d in path.iterdir():
            if d.is_file() and d.suffix != ".py":
                continue

            if d.name in ["__pycache__", "site-packages"]:
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

                logging.info(f"Importing plugin module {d}")

                module = importlib.util.module_from_spec(spec)
                sys.modules[d.stem] = module
                if spec.loader:
                    spec.loader.exec_module(module)

            except Exception:
                logging.exception(f"Failed to import plugin module {d}")

    def toggle_plugin(
        self,
        kls: type[Plugin]|str,
        enabled: bool,
        state: dict | None = None,
    ) -> Plugin | None:
        if isinstance(kls, str):
            try:
                kls = Plugin.get_class_by_name(kls)
            except ValueError:
                logging.warning(f"Couldn't find plugin class: {kls}")
                return None

        currently_enabled = kls.__name__ in self.plugins_by_class

        if enabled and not currently_enabled:
            logging.info(f"Enabling plugin {kls.__name__}")
            try:
                if state is None:
                    state = self.recording_settings.plugin_states.get(kls.__name__, {})

                plugin: Plugin = kls.from_dict(state)

                self.plugins_by_class[kls.__name__] = plugin
                self.main_window.settings_panel.add_plugin_settings(plugin)

                plugin.changed.connect(self.on_plugin_changed)

                if self.recording:
                    plugin.on_recording_loaded(self.recording)
            except Exception:
                logging.exception(f"Failed to enable plugin {kls}")
                return None

        elif not enabled and currently_enabled:
            logging.info(f"Disabling plugin {kls.__name__}")
            plugin = self.plugins_by_class[kls.__name__]

            plugin.on_disabled()
            del self.plugins_by_class[kls.__name__]
            self.main_window.settings_panel.remove_plugin_settings(kls.__name__)

        self.plugins = list(self.plugins_by_class.values())
        self.plugins.sort(key=lambda p: p.render_layer)

        self.main_window.video_widget.update()

    def on_plugin_changed(self) -> None:
        self.main_window.video_widget.update()
        self.save_settings()

    def run(self) -> int:
        if not self.headless:
            self.main_window.show()
            self.tray_icon.show()
            menu = self.main_window.get_menu("File", auto_create=False)
            context_menu = clone_menu(menu)
            self.tray_icon.setContextMenu(context_menu)

        return self.exec()

    def show_notification(
        self,
        title: str,
        message: str,
        icon: QSystemTrayIcon.MessageIcon|QIcon = QSystemTrayIcon.MessageIcon.Information,
        duration: int = 10000
    ) -> None:
        self.tray_icon.showMessage(title, message, icon, duration)

    @property
    def headless(self) -> bool:
        return self.args.job is not None

    def unload(self) -> None:
        self.set_playback_state(False)
        self.recording = None
        class_names = list(self.plugins_by_class.keys())
        for plugin_class_name in class_names:
            self.toggle_plugin(plugin_class_name, False)

        self.recording_unloaded.emit()

    def load(self, path: Path) -> None:
        """Load a recording from the given path."""
        self.unload()
        logging.info("Opening recording at path: %s", path)
        self.recording = nr.load(path)
        self.playback_start_anchor = 0

        self.main_window.on_recording_loaded(self.recording)

        try:
            settings_path = path / ".neon_player" / "settings.json"
            if settings_path.exists():
                logging.info(f"Loading recording settings from {settings_path}")
                self.recording_settings = RecordingSettings.from_dict(json.loads(settings_path.read_text()))

                if len(self.recording_settings.export_window) != 2:
                    logging.warning("Invalid export window in settings")
                    self.recording_settings.export_window = [
                        self.recording.start_time,
                        self.recording.stop_time,
                    ]

            else:
                self.recording_settings = RecordingSettings()
                self.recording_settings.export_window = [
                    self.recording.start_time,
                    self.recording.stop_time,
                ]

        except Exception:
            logging.exception("Failed to load settings")
            self.recording_settings = RecordingSettings()

        if self.settings.skip_gray_frames_on_load:
            self.seek_to(self.recording.scene[0].time)
        else:
            self.seek_to(self.recording.start_time)

        QTimer.singleShot(0, self.toggle_plugins_by_settings)
        QTimer.singleShot(10, self.main_window.timeline_dock.init_view)
        self.recording_settings.changed.connect(self.toggle_plugins_by_settings)
        self.recording_settings.changed.connect(self.save_settings)

        self.recording_loaded.emit(self.recording)

    def toggle_plugins_by_settings(self) -> None:
        for cls_name, enabled in self.recording_settings.enabled_plugins.items():
            state = self.recording_settings.plugin_states.get(cls_name, {})
            self.toggle_plugin(cls_name, enabled, state)

    def get_action(self, action_path: str) -> QAction:
        return self.main_window.get_action(action_path)

    def toggle_play(self) -> None:
        if self.recording is None:
            return

        if self.current_ts >= self.recording.stop_time:
            self.current_ts = self.recording.start_time

        if self.refresh_timer.isActive():
            self.refresh_timer.stop()

        else:
            self._reset_start_anchor()
            self.refresh_timer.start()

        self.playback_state_changed.emit(self.refresh_timer.isActive())

    def set_playback_speed(self, speed: float) -> None:
        self.playback_speed = speed
        self._reset_start_anchor()
        self.speed_changed.emit(speed)

    def _reset_start_anchor(self) -> None:
        if self.playback_speed == 0:
            return

        now = time.time_ns()
        elapsed_time = (self.current_ts - self.recording.start_time) / self.playback_speed
        self.playback_start_anchor = now - elapsed_time

    def set_playback_state(self, playing: bool) -> None:
        if self.is_playing != playing:
            self.toggle_play()

    def poll(self) -> None:
        if self.recording is None:
            return

        if self.playback_speed == 0:
            return

        now = time.time_ns()
        elapsed_time = (now - self.playback_start_anchor) * self.playback_speed
        target_ts = int(elapsed_time + self.recording.start_time)

        if self.recording.start_time <= target_ts <= self.recording.stop_time:
            self.current_ts = target_ts
            self.main_window.set_time_in_recording(self.current_ts)

        else:
            self.current_ts = min(max(target_ts, self.recording.start_time), self.recording.stop_time)
            self.main_window.set_time_in_recording(self.current_ts)

            self.refresh_timer.stop()
            self.playback_state_changed.emit(self.refresh_timer.isActive())

        self.position_changed.emit(self.current_ts)

    def seek_to(self, ts: int) -> None:
        if self.recording is None:
            return

        ts = min(max(int(ts), self.recording.start_time), self.recording.stop_time)

        now = time.time_ns()
        self.current_ts = ts
        self.playback_start_anchor = now - (ts - self.recording.start_time)
        self.main_window.set_time_in_recording(ts)

        self.position_changed.emit(self.current_ts)
        self.seeked.emit(self.current_ts)

    def render_to(self, painter: QPainter, ts: int | None = None) -> None:
        if ts is None:
            ts = self.current_ts

        brush = painter.brush()
        pen = painter.pen()
        font = painter.font()
        for plugin in self.plugins:
            plugin.render(painter, ts)
            painter.setBrush(brush)
            painter.setPen(pen)
            painter.setFont(font)
            painter.setOpacity(1.0)

    def export_all(self) -> None:
        if self.recording is None:
            return

        # ask user for export path
        export_path = QFileDialog.getExistingDirectory(
            self.main_window,
            "Select export directory",
            str(self.recording._rec_dir),
        )

        if not export_path:
            return

        for plugin in self.plugins:
            if hasattr(plugin, "export"):
                plugin.export(Path(export_path))

    @property
    def is_playing(self) -> bool:
        return self.refresh_timer.isActive()
