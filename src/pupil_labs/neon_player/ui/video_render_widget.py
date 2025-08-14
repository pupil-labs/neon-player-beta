
import time

from PySide6.QtCore import (
    QPoint,
    QPropertyAnimation,
    QSize,
    Qt,
)
from PySide6.QtGui import (
    QColorConstants,
    QPainter,
    QPaintEvent,
    QResizeEvent,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QLabel,
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

        self._last_frame_time = None
        self._fps = 0.0
        self.fps_label = QLabel(self)
        self.fps_label.resize(1024, 24)

        self.opacity_effect = QGraphicsOpacityEffect()
        self.fps_label.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(0.0)

        self.fade_anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_anim.setDuration(1000)
        self.fade_anim.setStartValue(1.0)
        self.fade_anim.setEndValue(0.0)
        self.fade_anim.finished.connect(self.on_fade_finished)

    def on_fade_finished(self):
        self._last_frame_time = None

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

        if neon_player.instance().settings.show_fps:
            now = time.monotonic()
            if self._last_frame_time is not None:
                delta = now - self._last_frame_time
                self.fade_anim.stop()
                instant_fps = 1.0 / delta
                self._fps = self._fps * 0.98 + instant_fps * 0.02
                self.fps_label.setText(f"{self._fps:.2f} fps")
                self.opacity_effect.setOpacity(1.0)
                self.fade_anim.start()

            self._last_frame_time = now

        neon_player.instance().render_to(painter)

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
