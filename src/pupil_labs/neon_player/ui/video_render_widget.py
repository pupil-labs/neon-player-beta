
import time

from PySide6.QtCore import (
    QPoint,
    QSize,
    Qt,
)
from PySide6.QtGui import (
    QColorConstants,
    QFont,
    QPainter,
    QPaintEvent,
    QResizeEvent,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (
    QWidget,
)

from pupil_labs import neon_player
from pupil_labs.neon_recording import NeonRecording


class VideoRenderWidget(QOpenGLWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(256, 256)

        # Ensure the widget has the proper format in high-DPI screens
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setAutoFillBackground(True)

        self.ts = 0
        self.scale = 1.0
        self.offset = QPoint(0, 0)

        self._last_frame_time = time.monotonic()
        self._fps = 0.0

    def on_recording_loaded(self, recording: NeonRecording) -> None:
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

        now = time.monotonic()
        delta = now - self._last_frame_time
        self._last_frame_time = now
        if delta > 0:
            instant_fps = 1.0 / delta
            self._fps = self._fps * 0.95 + instant_fps * 0.05

        neon_player.instance().render_to(painter)

        painter.resetTransform()
        painter.setFont(QFont("Arial", 16))
        painter.setPen(QColorConstants.White)
        painter.drawText(10, 20, f"FPS: {self._fps:.2f}")

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.adjust_size()

    def adjust_size(self) -> None:
        app = neon_player.instance()
        if app.recording is None:
            return

        source_size = QSize(
            app.recording.scene.width or 1, app.recording.scene.height or 1
        )
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
