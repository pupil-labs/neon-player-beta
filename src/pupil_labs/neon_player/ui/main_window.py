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
from pupil_labs.neon_player.ui.expander import ExpanderList
from pupil_labs.neon_player.ui.settings_panel import SettingsPanel
from pupil_labs.neon_recording import NeonRecording

from .console import ConsoleWindow
from .timeline_dock import TimelineDock
from .video_render_widget import VideoRenderWidget


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Neon Player")
        self.resize(1200, 800)

        neon_player.instance().setPalette(QPalette(QColor("#1c2021")))

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

            PreferencesDialog > QLabel {
                font-weight: bold;
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
        self.register_action("&File/&Preferences", "Ctrl+p", self.on_preferences_action)
        self.register_action("&File/&Quit", "Ctrl+q", self.on_quit_action)

        self.register_action("&View/&Console", "Ctrl+Alt+c", self.console_window.show)

        self.play_action = self.register_action(
            "&Playback/&Play\\Pause", "Space", self.on_play_action
        )

        self.settings_panel = SettingsPanel()
        self.add_dock(
            self.settings_panel, "Control Panel", Qt.DockWidgetArea.RightDockWidgetArea
        )

        self.timeline_dock = TimelineDock()
        self.add_dock(
            self.timeline_dock, "Timeline", Qt.DockWidgetArea.BottomDockWidgetArea
        )

        self.setCorner(
            Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)

    def on_open_action(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Open Recording")
        if path:
            neon_player.instance().load(Path(path))

    def on_preferences_action(self) -> None:
        preferences_dialog = PreferencesDialog(self)
        preferences_dialog.exec()

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

    def get_menu(self, menu_path: str, auto_create: bool = True) -> typing.Union[QMenu, QMenuBar]:
        menu: typing.Union[QMenu, QMenuBar] = self.menuBar()
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


class PreferencesDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(400, 400)

        app = neon_player.instance()

        self.setWindowTitle("Preferences")

        layout = QVBoxLayout(self)
        self.setLayout(layout)

        self.expander_list = ExpanderList()
        layout.addWidget(self.expander_list)

        general_settings_form = PropertyForm(app.settings)
        general_settings_form.property_changed.connect(self.on_property_changed)
        self.expander_list.add_expander(
            "Global Settings", general_settings_form, sort_key="000"
        )

        if app.recording is not None:
            class PluginListObject:
                pass

            for kls in Plugin.known_classes:
                def getter(self: PluginListObject, kls: type[Plugin] = kls) -> bool:
                    return kls.__name__ in app.recording_settings.enabled_plugin_names

                def setter(
                    self: PluginListObject, value: bool, kls: type[Plugin] = kls
                ) -> None:
                    app.toggle_plugin(kls, value)

                prop = property(getter, setter)
                label = kls.label if hasattr(kls, "label") else kls.__name__
                setattr(PluginListObject, label, prop)

            plugins_form = PropertyForm(PluginListObject())
            self.expander_list.add_expander("Enabled Plugins", plugins_form)

    def on_property_changed(self, prop_name: str, value: typing.Any) -> None:
        neon_player.instance().save_settings()

    def on_plugin_state_changed(
        self, plugin_class: type[Plugin], checked: bool
    ) -> None:
        neon_player.instance().toggle_plugin(plugin_class, checked)
