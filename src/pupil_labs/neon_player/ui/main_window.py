import typing
import webbrowser
from pathlib import Path

from PySide6.QtCore import (
    Qt,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QPalette,
)
from PySide6.QtWidgets import (
    QDialog,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)
from qt_property_widgets.widgets import PropertyForm

from pupil_labs import neon_player
from pupil_labs.neon_player import Plugin
from pupil_labs.neon_player.ui import QtShortcutType
from pupil_labs.neon_player.ui.settings_panel import SettingsPanel
from pupil_labs.neon_recording import NeonRecording

from .console import ConsoleWindow
from .timeline_dock import TimeLineDock
from .video_render_widget import VideoRenderWidget


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Neon Player")
        self.resize(1600, 1000)

        app = neon_player.instance()
        app.setPalette(QPalette(QColor("#1c2021")))

        self.setStyleSheet("""
            QWidget {
                font-family: arial;
                font-size: 11pt;
            }

            Expander {
                border-top: 0;
                border-bottom: 2px solid #494d4d;
            }

            Expander>QLabel {
                font-weight: bold;
            }

            Expander>QToolButton {
                border: none;
                font-family: monospace;
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

            ValueListItemWidget>QPushButton {
                width: 24px;
                height: 20px;
                border-radius: 5px;
                border: 1px solid #555;
                background-color: #440808;
            }

            ValueListItemWidget>QPushButton::hover {
                background-color: #c11;
            }
        """)

        self.video_widget = VideoRenderWidget()
        self.setCentralWidget(self.video_widget)

        self.job_status_label = QLabel()

        self.statusBar().addWidget(self.job_status_label)

        self.console_window = ConsoleWindow()

        self.register_action(
            "&Help/&Online Documentation", on_triggered=self.on_documentation_action
        )
        self.register_action("&Help/&About", on_triggered=self.on_about_action)

        self.register_action("&File/&Open", "Ctrl+o", self.on_open_action)
        self.register_action("&File/&Global Settings", None, self.show_global_settings)
        self.rec_settings_action = self.register_action(
            "&File/&Recording Settings",
            None,
            self.show_recording_settings
        )
        self.rec_settings_action.setDisabled(True)
        self.register_action("&File/&Quit", "Ctrl+q", self.on_quit_action)

        self.register_action("&View/&Console", "Ctrl+Alt+c", self.console_window.show)

        self.play_action = self.register_action(
            "&Playback/&Play\\Pause", "Space", self.on_play_action
        )

        self.settings_panel = SettingsPanel()
        self.add_dock(
            self.settings_panel, "Control Panel", Qt.DockWidgetArea.RightDockWidgetArea
        )

        self.timeline_dock = TimeLineDock()
        self.add_dock(
            self.timeline_dock, "Timeline", Qt.DockWidgetArea.BottomDockWidgetArea
        )

        self.setCorner(
            Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)

        app.recording_loaded.connect(
            lambda recording: self.rec_settings_action.setDisabled(recording is None)
        )

    def on_open_action(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Open Recording")
        if path:
            neon_player.instance().load(Path(path))

    def show_global_settings(self) -> None:
        dialog = GlobalSettingsDialog(self)
        dialog.exec()

    def show_recording_settings(self) -> None:
        if neon_player.instance().recording is None:
            QMessageBox.information(
                self, "Neon Player - Recording Settings", "Please open a recording."
            )

            return

        dialog = RecordingSettingsDialog(self)
        dialog.exec()

    def on_quit_action(self) -> None:
        self.close()

    def on_play_action(self) -> None:
        neon_player.instance().toggle_play()

    def on_documentation_action(self) -> None:
        webbrowser.open("https://docs.pupil-labs.com/neon/neon-player/")

    def on_about_action(self) -> None:
        QMessageBox.about(
            self,
            "About Neon Player vX.y.z",
            (
                "Neon Player\nVersion X.y.z\n\n"
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

    def add_dock(
        self,
        widget: QWidget,
        title: str,
        area: Qt.DockWidgetArea = Qt.DockWidgetArea.LeftDockWidgetArea,
    ) -> QDockWidget:
        dock = QDockWidget(title, self)
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

        global_settings_form = PropertyForm(app.settings)
        global_settings_form.property_changed.connect(self.on_property_changed)

        layout.addWidget(QLabel("<h2>Global Settings</h2>"))
        layout.addWidget(global_settings_form)

        layout.addWidget(QLabel("<h2>Plugin Settings</h2>"))
        for cls in Plugin.known_classes:
            if cls.global_properties is not None:
                plugin_props_form = PropertyForm(cls.global_properties)
                plugin_props_form.property_changed.connect(self.on_property_changed)
                layout.addWidget(QLabel(f"<h3>{cls.get_label()}</h3>"))
                layout.addWidget(plugin_props_form)

    def on_property_changed(self, prop_name: str, value: typing.Any) -> None:
        neon_player.instance().save_settings()


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
