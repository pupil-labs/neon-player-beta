import typing
import webbrowser
from pathlib import Path

from pupil_labs.neon_recording import NeonRecording
from PySide6.QtCore import (
    Qt,
    QUrl,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
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
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)
from qt_property_widgets.expander import ExpanderList
from qt_property_widgets.widgets import PropertyForm

from pupil_labs import neon_player
from pupil_labs.neon_player import Plugin
from pupil_labs.neon_player.ui import QtShortcutType
from pupil_labs.neon_player.ui.console import ConsoleWindow
from pupil_labs.neon_player.ui.settings_panel import SettingsPanel
from pupil_labs.neon_player.ui.timeline_dock import TimeLineDock
from pupil_labs.neon_player.ui.video_render_widget import VideoRenderWidget
from pupil_labs.neon_player.utilities import SlotDebouncer


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Neon Player")
        self.setAcceptDrops(True)
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

            Expander Expander {
                border-bottom: none;
            }

            Expander>QLabel {
                font-weight: bold;
            }

            Expander Expander>QLabel {
                font-weight: normal;
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
        """)

        self.greeting_label = QLabel("""
            <h1>Welcome to Neon Player!</h1>
            <p>
                To get started, drag and drop a recording folder here or
                <a href="action:File/Open recording">browse to a recording folder</a>.
            </p>
            <p>
                Visit our <a href="https://docs.pupil-labs.com/neon/neon-player/">
                online documentation</a> for help and more information.
            </p>
        """, parent=self)
        self.greeting_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.greeting_label.setStyleSheet("background: #000000")
        self.greeting_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.greeting_label.linkActivated.connect(self.on_greeting_link_clicked)

        self.video_widget = VideoRenderWidget()

        self.greeting_switcher = QStackedLayout()
        central_widget = QWidget(self)
        central_widget.setLayout(self.greeting_switcher)
        self.greeting_switcher.addWidget(self.greeting_label)
        self.greeting_switcher.addWidget(self.video_widget)
        self.setCentralWidget(central_widget)

        app.recording_loaded.connect(self.on_recording_opened)
        app.recording_unloaded.connect(self.on_recording_closed)

        self.job_status_label = QLabel()

        self.statusBar().addWidget(self.job_status_label)

        self.console_window = ConsoleWindow()
        self.settings_panel = SettingsPanel()
        self.settings_dock = self.add_dock(
            self.settings_panel, "Control Panel", Qt.DockWidgetArea.RightDockWidgetArea
        )

        self.timeline = TimeLineDock()
        self.timeline_dock = self.add_dock(
            self.timeline, "Timeline", Qt.DockWidgetArea.BottomDockWidgetArea
        )

        self.register_action(
            "&Help/&Online Documentation", on_triggered=self.on_documentation_action
        )
        self.register_action("&Help/&About", on_triggered=self.on_about_action)

        self.register_action("&File/&Open recording", "Ctrl+o", self.on_open_action)
        self.register_action("&File/&Close recording", "Ctrl+w", app.unload)
        self.register_action("&File/&Global Settings", None, self.show_global_settings)
        self.rec_settings_action = self.register_action(
            "&File/&Recording Settings",
            None,
            self.show_recording_settings
        )
        self.rec_settings_action.setDisabled(True)
        self.register_action(
            "&File/&Export All", on_triggered=app.export_all
        )
        self.register_action("&File/&Quit", "Ctrl+q", self.on_quit_action)

        self.register_action("&Tools/&Console", "Ctrl+Alt+c", self.console_window.show)
        self.register_action(
            "&Tools/&Browse recording folder", None, self.on_show_recording_folder
        )
        self.register_action(
            "&Tools/Browse recording &settings and cache folder",
            None,
            self.on_show_recording_cache
        )

        self.play_action = self.register_action(
            "&Playback/&Play\\Pause", "Space", self.on_play_action
        )

        self.register_action(
            "&Timeline/&Reset view", None, self.timeline.reset_view
        )

        self.setCorner(
            Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)

        app.recording_loaded.connect(
            lambda recording: self.rec_settings_action.setDisabled(recording is None)
        )

        self.on_recording_closed()

    def on_greeting_link_clicked(self, link: str):
        if link.startswith("action:"):
            action = self.get_action(link[7:])
            if action:
                action.trigger()

        else:
            QDesktopServices.openUrl(QUrl(link))

    def on_recording_opened(self):
        self.greeting_switcher.setCurrentIndex(1)
        self.timeline_dock.show()
        self.settings_dock.show()
        self.menuBar().show()
        self.statusBar().show()

    def on_recording_closed(self):
        self.greeting_switcher.setCurrentIndex(0)
        self.timeline_dock.hide()
        self.settings_dock.hide()
        self.menuBar().hide()
        self.statusBar().hide()

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
        # Accept directories only
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if len(urls) == 1 and urls[0].isLocalFile() and urls[0].toLocalFile():
                path = Path(urls[0].toLocalFile())
                if path.is_dir():
                    event.acceptProposedAction()
                    return

        event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            path = Path(urls[0].toLocalFile())
            if path.is_dir():
                neon_player.instance().load(path)
                event.acceptProposedAction()
                return

        event.ignore()

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
        layout.addWidget(QLabel("<h2>Global Settings</h2>"))
        layout.addWidget(expander_list)

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
