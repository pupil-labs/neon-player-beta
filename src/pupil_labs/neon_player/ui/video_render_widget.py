
import time

from pupil_labs.neon_recording import NeonRecording
from PySide6.QtCore import QPoint, QPointF, QPropertyAnimation, QSize, Qt, Signal
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


class ScalingWidget(QOpenGLWidget):
    scaled_clicked = Signal(float, float)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.source_size = QSize(100, 100)
        self.scaled_children_positions = {}
        self._mouse_down = False

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

        self.offset = QPointF(0, 0)
        self.scale = 1.0

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._mouse_down = True

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._mouse_down:
                pos = event.pos() - self.offset
                self.scaled_clicked.emit(
                    pos.x() / self.scale,
                    pos.y() / self.scale
                )

            self._mouse_down = False

    def on_fade_finished(self):
        self._last_frame_time = None

    def map_point(self, point: QPoint|QPointF) -> QPointF:
        point = QPointF(point) - self.offset
        return QPointF(
            point.x() / self.scale,
            point.y() / self.scale
        )

    def transform_painter(self, painter: QPainter) -> None:
        painter.translate(self.offset)
        painter.scale(self.scale, self.scale)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        painter.fillRect(0, 0, self.width(), self.height(), QColorConstants.Black)

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

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.adjust_size()
        for child in self.children():
            self.update_child_position(child)

    def adjust_size(self) -> None:
        app = neon_player.instance()
        if app.recording is None:
            return

        self.fit_rect()
        self.repaint()

    def fit_rect(self, source_size: QSize|None = None) -> None:
        if source_size is not None:
            self.source_size = source_size

        source_aspect = self.source_size.width() / self.source_size.height()
        target_aspect = self.width() / self.height()

        if source_aspect > target_aspect:
            self.scale = self.width() / self.source_size.width()
            self.offset = QPointF(
                0, int((self.height() - self.source_size.height() * self.scale) / 2.0)
            )

        else:
            self.scale = self.height() / self.source_size.height()
            self.offset = QPointF(
                int((self.width() - self.source_size.width() * self.scale) / 2.0), 0
            )

    def set_child_scaled_pos(self, child: QWidget, x: float, y: float) -> None:
        self.scaled_children_positions[child] = (x, y, False)
        self.update_child_position(child)

    def set_child_scaled_center(self, child: QWidget, x: float, y: float) -> None:
        self.scaled_children_positions[child] = (x, y, True)
        self.update_child_position(child)

    def update_child_position(self, child: QWidget) -> None:
        if child not in self.scaled_children_positions:
            return

        x, y, centered = self.scaled_children_positions[child]

        x *= self.scale
        y *= self.scale

        if centered:
            x -= child.width() / 2
            y -= child.height() / 2

        child.move(QPoint(
            int(x + self.offset.x()),
            int(y + self.offset.y())
        ))


class VideoRenderWidget(ScalingWidget):
    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.ts = None

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        self.source_size = QSize(
            recording.scene.width,
            recording.scene.height
        )
        self.adjust_size()
        self.repaint()

    def set_time_in_recording(self, ts: int) -> None:
        self.ts = ts
        self.repaint()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        self.transform_painter(painter)

        neon_player.instance().render_to(painter)
