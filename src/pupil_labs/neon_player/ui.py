import typing
import webbrowser

from PySide6.QtCore import (
    QKeyCombination,
    QPoint,
    QSize,
    Qt,
)
from PySide6.QtGui import (
    QAction,
    QColorConstants,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QResizeEvent,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QWidget,
)

from pupil_labs import neon_player
from pupil_labs.neon_player.settings_panel import SettingsPanel
from pupil_labs.neon_recording import NeonRecording

from .console import ConsoleWindow

QtShortcutType = typing.Optional[
    typing.Union[QKeySequence, QKeyCombination, QKeySequence.StandardKey, str, int]
]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Neon Player")
        self.resize(1200, 800)

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
        self.register_action("&File/&Quit", "Ctrl+q", self.on_quit_action)

        self.register_action("&View/&Console", "Ctrl+Alt+c", self.console_window.show)

        self.play_action = self.register_action(
            "&Playback/&Play\\Pause", "Space", self.on_play_action
        )

        self.settings_panel = SettingsPanel()
        self.add_dock(
            self.settings_panel, "Settings", Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.setCorner(Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.RightDockWidgetArea)
        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)

    def on_open_action(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Open Recording")
        if path:
            app = neon_player.instance()
            app.load(path)

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

    def get_menu(self, menu_path: str) -> typing.Union[QMenu, QMenuBar]:
        menu: typing.Union[QMenu, QMenuBar] = self.menuBar()
        parts = menu_path.split("/")
        for depth, part in enumerate(parts):
            for action in menu.actions():
                text_matches = action.text().replace("&", "") == part.replace("&", "")
                if action.menu() is not None and text_matches:
                    menu = action.menu()  # type: ignore
                    break
            else:
                new_menu = QMenu(part, menu)

                if depth == 0 and len(menu.actions()) > 0:
                    menu.insertMenu(menu.actions()[-1], new_menu)
                else:
                    menu.addMenu(new_menu)

                menu = new_menu

        return menu

    def get_action(self, action_path: str) -> typing.Optional[QAction]:
        menu_path, action_name = action_path.rsplit("/", 1)
        menu = self.get_menu(menu_path)

        for action in menu.actions():
            if action.text().replace("&", "") == action_name.replace("&", ""):
                return action

        return None

    def register_action(
        self,
        action_path: str,
        shortcut: QtShortcutType = None,
        on_triggered: typing.Optional[typing.Callable] = None,
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
        self.addDockWidget(area, dock)

        return dock

    def set_time_in_recording(self, ts: int) -> None:
        self.video_widget.set_time_in_recording(ts)

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        self.video_widget.on_recording_loaded(recording)


class VideoRenderWidget(QOpenGLWidget):
    def __init__(self, parent: typing.Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(256, 256)

        # Ensure the widget has the proper format in high-DPI screens
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setAutoFillBackground(True)

        self.ts = 0
        self.scale = 1.0
        self.offset = QPoint(0, 0)

    def on_recording_loaded(self, recording: typing.Optional[NeonRecording]) -> None:
        self.adjust_size()

    def set_time_in_recording(self, ts: int) -> None:
        self.ts = ts
        self.repaint()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        painter.fillRect(0, 0, self.width(), self.height(), QColorConstants.Black)

        painter.translate(self.offset)
        painter.scale(self.scale, self.scale)

        if self.ts is None:
            return

        app = neon_player.instance()
        app.render_to(painter)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.adjust_size()

    def adjust_size(self) -> None:
        app = neon_player.instance()
        if app.recording is None:
            return

        source_size = QSize(app.recording.scene.width, app.recording.scene.height)
        self.fit_rect(source_size)
        self.repaint()

    def fit_rect(self, source_size: QSize) -> None:
        source_aspect = source_size.width() / source_size.height()
        target_aspect = self.width() / self.height()

        if source_aspect > target_aspect:
            self.scale = self.width() / source_size.width()
            self.offset = QPoint(
                0, int((self.height() - source_size.height() * self.scale) / 2.0)
            )

        else:
            self.scale = self.height() / source_size.height()
            self.offset = QPoint(
                int((self.width() - source_size.width() * self.scale) / 2.0), 0
            )
