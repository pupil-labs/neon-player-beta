import logging
import typing
import webbrowser
from pathlib import Path

from pupil_labs.neon_recording import NeonRecording
from PySide6.QtCore import (
    QKeyCombination,
    Qt,
    QTimer,
    QUrl,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QPalette,
    QPixmap,
)
from PySide6.QtUiTools import loadUiType
from PySide6.QtWidgets import (
    QDialog,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)
from qt_property_widgets.expander import ExpanderList
from qt_property_widgets.widgets import PropertyForm

from pupil_labs import neon_player
from pupil_labs.neon_player import Plugin, asset_path
from pupil_labs.neon_player.ui import QtShortcutType
from pupil_labs.neon_player.ui.console import LOG_COLORS, ConsoleWindow
from pupil_labs.neon_player.ui.settings_panel import SettingsPanel
from pupil_labs.neon_player.ui.timeline_dock import TimeLineDock
from pupil_labs.neon_player.ui.video_render_widget import VideoRenderWidget
from pupil_labs.neon_player.utilities import SlotDebouncer

Ui_Class, QtBaseClass = loadUiType(str(asset_path("splash.ui")))

class SplashWidget(Ui_Class, QtBaseClass):
    def __init__(self) -> None:
        super().__init__()
        self.setupUi(self)
        self.logo.setPixmap(QPixmap(asset_path("Primary-White-76px.png")))
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:
        # Accept directories only
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if len(urls) == 1 and urls[0].isLocalFile() and urls[0].toLocalFile():
                path = Path(urls[0].toLocalFile())
                if path.is_dir():
                    event.acceptProposedAction()
                    self.dropbox.setStyleSheet("#dropbox { background: #141414 }")
                    return

        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self.dropbox.setStyleSheet("#dropbox { background: #080808 }")

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            path = Path(urls[0].toLocalFile())
            if path.is_dir():
                neon_player.instance().load(path)
                event.acceptProposedAction()
                return

        event.ignore()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        app = neon_player.instance()
        self.setWindowTitle(f"{app.applicationName()} - v{app.applicationVersion()}")
        self.setAcceptDrops(True)
        self.resize(1600, 1000)

        app.setPalette(QPalette(QColor("#1c2021")))

        app.setStyleSheet("""
            QWidget {
                font-family: arial;
                font-size: 11pt;
            }

            Expander {
                border-top: 0;
                border-bottom: 2px solid #494d4d;
            }

            Expander Expander {
                border-bottom: none;
            }

            Expander>QLabel {
                font-weight: bold;
            }

            Expander Expander>QLabel {
                font-weight: normal;
            }

            Expander>QToolButton#HeaderAction {
                background-color: #6d7be0;
                border: none;
                border-radius: 4px;
            }

            ConsoleWindow>QTextEdit {
                font-family: 'Menlo', 'Monico', 'Consolas', 'Lucida Console', 'monospace', 'Courier New', 'Courier';
            }

            TimestampLabel {
                font-weight: bold;
                font-size: 16pt;
            }

            BoolWidget>QToolButton {
                width: 24px;
                height: 20px;
                border-radius: 5px;
                border: 1px solid #555;
                background-color: #111;
            }

            BoolWidget>QToolButton:checked {
                background: #6d7be0;
                border: 1px solid #555;
            }

            QDockWidget::title {
                background-color: #0f1314;
                padding: 5px;
            }

            TextWidget>QLineEdit {
                height: 24px;
                border-radius: 5px;
                border: 1px solid #555;
                background-color: #111;
            }

            QStatusBar {
                border-top: 1px solid #333;
            }

            QStatusBar > QPushButton {
                text-align: left;
                padding: 5px 10px;
            }
        """)

        self.splash_widget = SplashWidget()
        self.splash_widget.browse_button.clicked.connect(self.on_open_action)

        self.video_widget = VideoRenderWidget()

        self.greeting_switcher = QStackedLayout()
        central_widget = QWidget(self)
        central_widget.setLayout(self.greeting_switcher)
        self.greeting_switcher.addWidget(self.splash_widget)
        self.greeting_switcher.addWidget(self.video_widget)
        self.setCentralWidget(central_widget)

        app.recording_loaded.connect(self.on_recording_opened)
        app.recording_unloaded.connect(self.on_recording_closed)

        self.status_label = QPushButton()
        self.status_label.setFlat(True)
        self.status_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.job_progress_bar = QProgressBar()
        self.job_progress_bar.hide()
        self.job_progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.statusBar().addWidget(self.status_label, stretch=5)
        self.statusBar().addWidget(self.job_progress_bar, stretch=1)
        app.job_manager.updated.connect(self.update_job_status)

        self.log_status_handler = StatusBarLogHandler(self.status_label)
        logging.getLogger().addHandler(self.log_status_handler)

        self.console_window = ConsoleWindow()
        self.settings_panel = SettingsPanel()
        self.settings_dock = self.add_dock(
            self.settings_panel, "", Qt.DockWidgetArea.RightDockWidgetArea
        )

        self.timeline = TimeLineDock()
        self.timeline_dock = self.add_dock(
            self.timeline, "", Qt.DockWidgetArea.BottomDockWidgetArea
        )

        self.register_action(
            "&Help/&Online Documentation", on_triggered=self.on_documentation_action
        )
        self.register_action("&Help/&About", on_triggered=self.on_about_action)

        self.register_action("&File/&Open recording", "Ctrl+o", self.on_open_action)
        self.register_action("&File/&Close recording", "Ctrl+w", app.unload)
        self.register_action("&File/&Global Settings", None, self.show_global_settings)
        self.register_action("&File/&Quit", "Ctrl+q", self.on_quit_action)

        self.register_action("&Tools/&Console", "Ctrl+Alt+c", self.console_window.show)
        self.register_action("&Tools/&Reset docks", None, self.reset_docks)
        self.register_action(
            "&Tools/&Browse recording folder", None, self.on_show_recording_folder
        )
        self.register_action(
            "&Tools/Browse recording &settings and cache folder",
            None,
            self.on_show_recording_cache
        )

        self.playback_actions = [
            self.register_action(
                "&Playback/&Play\\Pause", "Space", self.on_play_action
            ),
            self.register_action(
                "&Playback/Skip forward 5s", Qt.Key.Key_Right, lambda: app.seek_by(5e9)
            ),
            self.register_action(
                "&Playback/Skip backwards 5s", Qt.Key.Key_Left, lambda: app.seek_by(-5e9)
            ),
            self.register_action(
                "&Playback/Next scene frame",
                QKeyCombination(Qt.KeyboardModifier.ShiftModifier, Qt.Key.Key_Right),
                lambda: app.seek_by_frame(1)
            ),
            self.register_action(
                "&Playback/Previous scene frame",
                QKeyCombination(Qt.KeyboardModifier.ShiftModifier, Qt.Key.Key_Left),
                lambda: app.seek_by_frame(-1)
            ),
        ]

        self.register_action(
            "&Timeline/&Reset view", None, self.timeline.reset_view
        )

        self.setCorner(
            Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)

        self.on_recording_closed()
        self.status_label.clicked.connect(self.console_window.show)

    def reset_docks(self):
        docks_and_areas = {
            self.timeline_dock: Qt.DockWidgetArea.BottomDockWidgetArea,
            self.settings_dock: Qt.DockWidgetArea.RightDockWidgetArea
        }

        for dock, area in docks_and_areas.items():
            self.addDockWidget(area, dock)
            dock.setFloating(False)
            dock.show()

    def on_recording_opened(self):
        self.greeting_switcher.setCurrentIndex(1)
        self.timeline_dock.show()
        self.settings_dock.show()
        self.menuBar().show()
        self.statusBar().show()
        QTimer.singleShot(1, self.timeline.reset_view)

    def on_recording_closed(self):
        self.greeting_switcher.setCurrentIndex(0)
        self.timeline_dock.hide()
        self.settings_dock.hide()
        self.menuBar().hide()
        self.statusBar().hide()

    def update_job_status(self) -> None:
        job_manager = neon_player.instance().job_manager

        job_count = len(job_manager.current_jobs)
        if job_count == 0:
            self.job_progress_bar.hide()

        else:
            self.job_progress_bar.show()

            if job_count == 1:
                job = job_manager.current_jobs[0]
                if job.progress > 0:
                    self.job_progress_bar.setRange(0, 100)
                    self.job_progress_bar.setValue(100 * job.progress)
                    self.job_progress_bar.setFormat(f"{job.name} - %p%")
                else:
                    self.job_progress_bar.setRange(0, 0)

            else:
                self.job_progress_bar.setRange(0, 0)

        self.job_progress_bar.setTextVisible(True)

    def on_open_action(self) -> None:
        app = neon_player.instance()
        was_playing = app.is_playing
        app.set_playback_state(False)

        path = QFileDialog.getExistingDirectory(self, "Open Recording")
        if path:
            neon_player.instance().load(Path(path))
        else:
            app.set_playback_state(was_playing)

    def on_close_action(self) -> None:
        neon_player.instance().unload()

    def show_global_settings(self) -> None:
        dialog = GlobalSettingsDialog(self)
        dialog.resize(500, 600)
        dialog.exec()

    def on_quit_action(self) -> None:
        self.close()

    def on_show_recording_folder(self) -> None:
        app = neon_player.instance()
        if app.recording is None:
            return

        url = QUrl.fromLocalFile(str(app.recording._rec_dir))
        QDesktopServices.openUrl(url)

    def on_show_recording_cache(self) -> None:
        app = neon_player.instance()
        if app.recording is None:
            return

        url = QUrl.fromLocalFile(str(app.recording._rec_dir / ".neon_player"))
        QDesktopServices.openUrl(url)

    def dragEnterEvent(self, event):
        return self.splash_widget.dragEnterEvent(event)

    def dropEvent(self, event):
        return self.splash_widget.dropEvent(event)

    def on_play_action(self) -> None:
        neon_player.instance().toggle_play()

    def on_documentation_action(self) -> None:
        webbrowser.open("https://docs.pupil-labs.com/neon/neon-player/")

    def on_about_action(self) -> None:
        app = neon_player.instance()

        QMessageBox.about(
            self,
            f"About {app.applicationName()}",
            (
                f"{app.applicationName()}\nv{app.applicationVersion()}\n\n"
                "A Neon recording analysis application by Pupil Labs."
            ),
        )

    def get_menu(self, menu_path: str, auto_create: bool = True) -> QMenu | QMenuBar:
        menu: QMenu | QMenuBar = self.menuBar()
        parts = menu_path.split("/")
        for depth, part in enumerate(parts):
            for action in menu.actions():
                text_matches = action.text().replace("&", "") == part.replace("&", "")
                if action.menu() is not None and text_matches:
                    menu = action.menu()  # type: ignore
                    break
            else:
                if not auto_create:
                    return None

                new_menu = QMenu(part, menu)

                if depth == 0 and len(menu.actions()) > 0:
                    menu.insertMenu(menu.actions()[-1], new_menu)
                else:
                    menu.addMenu(new_menu)

                menu = new_menu

        return menu

    def get_action(self, action_path: str) -> QAction:
        menu_path, action_name = action_path.rsplit("/", 1)
        menu = self.get_menu(menu_path)

        for action in menu.actions():
            if action.text().replace("&", "") == action_name.replace("&", ""):
                return action

        raise ValueError(f"Action {action_path} not found")

    def sort_action_menu(self, menu_path: str):
        menu = self.get_menu(menu_path)
        sorted_actions = sorted(menu.actions(), key=lambda a: a.text().lower())
        for action in sorted_actions:
            shortcut = action.shortcut()
            menu.removeAction(action)
            menu.addAction(action)
            action.setShortcut(shortcut)

    def register_action(
        self,
        action_path: str,
        shortcut: QtShortcutType = None,
        on_triggered: typing.Callable | None = None,
    ) -> QAction:
        menu_path, action_name = action_path.rsplit("/", 1)

        menu = self.get_menu(menu_path)
        action = menu.addAction(action_name)

        if shortcut is not None:
            action.setShortcut(shortcut)

        if on_triggered is not None:
            action.triggered.connect(on_triggered)

        return action

    def unregister_action(self, action_path: str):
        menu_path, action_name = action_path.rsplit("/", 1)

        menu = self.get_menu(menu_path)
        for action in menu.actions():
            if action.text().replace("&", "") == action_name.replace("&", ""):
                menu.removeAction(action)
                break

    def add_dock(
        self,
        widget: QWidget,
        title: str,
        area: Qt.DockWidgetArea = Qt.DockWidgetArea.LeftDockWidgetArea,
    ) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        dock.setWidget(widget)
        dock.setFeatures(dock.features() & ~QDockWidget.DockWidgetClosable)
        self.addDockWidget(area, dock)

        return dock

    def set_time_in_recording(self, ts: int) -> None:
        self.video_widget.set_time_in_recording(ts)

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        self.video_widget.on_recording_loaded(recording)


class GlobalSettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Neon Player -Global Settings")

        app = neon_player.instance()

        layout = QVBoxLayout(self)
        self.setLayout(layout)

        expander_list = ExpanderList(self)
        scroll_area = QScrollArea()
        scroll_area.setWidget(expander_list)
        scroll_area.setWidgetResizable(True)

        layout.addWidget(QLabel("<h2>Global Settings</h2>"))
        layout.addWidget(scroll_area)

        global_settings_form = PropertyForm(app.settings)
        SlotDebouncer.debounce(
            app.settings.changed,
            neon_player.instance().save_settings
        )

        expander_list.add_expander("General", global_settings_form)

        for cls in Plugin.known_classes:
            if cls.global_properties is not None:
                plugin_props_form = PropertyForm(cls.global_properties)
                SlotDebouncer.debounce(
                    plugin_props_form.changed,
                    neon_player.instance().save_settings
                )
                expander_list.add_expander(
                    f"Plugin: {cls.get_label()}",
                    plugin_props_form
                )


class RecordingSettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Neon Player - Recording Settings")
        self.setMinimumSize(400, 400)

        app = neon_player.instance()

        layout = QVBoxLayout(self)
        self.setLayout(layout)

        layout.addWidget(QLabel("<h2>Recording Settings</h2>"))

        recording_settings_form = PropertyForm(app.recording_settings)
        layout.addWidget(recording_settings_form)


class StatusBarLogHandler(logging.Handler):
    def __init__(self, label: QWidget) -> None:
        super().__init__()
        self.label = label

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelname == "DEBUG":
            return

        msg = self.format(record)
        msg = msg.split("\n")[0]

        if record.levelname == "ERROR":
            msg = f"❗ {msg}"
        elif record.levelname == "WARNING":
            msg = f"⚠️ {msg}"
        elif msg == "Settings saved":
            msg = f"💾 {msg}"

        color = LOG_COLORS[record.levelname].name
        self.label.setStyleSheet(f"color: {color}")
        self.label.setText(msg)
