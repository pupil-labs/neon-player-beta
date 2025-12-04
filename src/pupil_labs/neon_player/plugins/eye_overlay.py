from enum import Flag, auto

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from qt_property_widgets.utilities import property_params

from pupil_labs import neon_player
from pupil_labs.neon_player.utilities import qimage_from_frame


class ModifyDirection(Flag):
    TOP = auto()
    RIGHT = auto()
    BOTTOM = auto()
    LEFT = auto()
    MOVE = auto()


class EyeOverlayPlugin(neon_player.Plugin):
    label = "Eye Overlay"

    def __init__(self) -> None:
        super().__init__()

        self._offset_x = 0.02
        self._offset_y = 0.02
        self._scale = 1.0
        self._opacity = 1.0

        self._border_width = 3
        self._border_color = QColor("#aaaaaa")

        self._mouse_mode = ModifyDirection(0)
        self._drag_position = None
        self.start_geometry = QRectF()
        self.video_widget = self.app.main_window.video_widget
        self.video_widget.mouse_moved.connect(self.on_mouse_moved)
        self.video_widget.mouse_pressed.connect(self.on_mouse_pressed)

    def on_mouse_pressed(self, event) -> None:
        self._drag_position = self.video_widget.map_point(event.pos())
        self.start_geometry = self.get_rect()

    def on_mouse_moved(self, event) -> None:
        if event.buttons() == Qt.LeftButton:
            self.on_drag(event)
        else:
            self.on_hover(event)

    def align(self, rect, corner):
        v = getattr(self.start_geometry, corner)()
        getattr(rect, f"move{corner.title()}")(v)

    def on_drag(self, event) -> None:
        mapped_pos = self.video_widget.map_point(event.pos())
        offset = mapped_pos - self._drag_position
        if self._mouse_mode == ModifyDirection.MOVE:
            self.offset_x += offset.x() / self.recording.scene.width
            self.offset_y += offset.y() / self.recording.scene.height
            self._drag_position = mapped_pos

        else:
            rect = QRectF(self.start_geometry)
            fix_y = False

            aligns = []
            if self._mouse_mode & ModifyDirection.LEFT:
                aligns.append("right")
                rect.setLeft(rect.left() + offset.x())
                fix_y = True
            elif self._mouse_mode & ModifyDirection.RIGHT:
                aligns.append("left")
                fix_y = True
                rect.setRight(rect.right() + offset.x())

            if self._mouse_mode & ModifyDirection.TOP:
                aligns.append("bottom")
                rect.setTop(rect.top() + offset.y())
            elif self._mouse_mode & ModifyDirection.BOTTOM:
                aligns.append("top")
                rect.setBottom(rect.bottom() + offset.y())

            if fix_y:
                self.scale = max(0.2, rect.width() / self.recording.eye.width)
                rect.setHeight(self.scale *  self.recording.eye.height)
            else:
                self.scale = max(0.2, rect.height() / self.recording.eye.height)
                rect.setWidth(self.scale *  self.recording.eye.width)

            for a in aligns:
                self.align(rect, a)

            self.offset_x = rect.left() / self.recording.scene.width
            self.offset_y = rect.top() / self.recording.scene.height

        self.changed.emit()
        self.video_widget.update()

    def on_hover(self, event) -> None:
        edge_margin = 20

        pos = self.video_widget.map_point(event.pos())
        rect = self.get_rect()

        if rect.contains(pos):
            self._mouse_mode = ModifyDirection(0)
            if pos.x() < rect.left() + edge_margin:
                self._mouse_mode |= ModifyDirection.LEFT
            elif pos.x() > rect.right() - edge_margin:
                self._mouse_mode |= ModifyDirection.RIGHT

            if pos.y() < rect.top() + edge_margin:
                self._mouse_mode |= ModifyDirection.TOP
            elif pos.y() > rect.bottom() - edge_margin:
                self._mouse_mode |= ModifyDirection.BOTTOM

            if self._mouse_mode == ModifyDirection(0):
                self._mouse_mode = ModifyDirection.MOVE
        else:
            self._mouse_mode = ModifyDirection(0)

        self._update_cursor()

    def _update_cursor(self):
        if self._mouse_mode == ModifyDirection(0):
            self.video_widget.unsetCursor()

        else:
            tl = self._mouse_mode == (ModifyDirection.TOP | ModifyDirection.LEFT)
            br = self._mouse_mode == (ModifyDirection.BOTTOM | ModifyDirection.RIGHT)
            tr = self._mouse_mode == (ModifyDirection.TOP | ModifyDirection.RIGHT)
            bl = self._mouse_mode == (ModifyDirection.BOTTOM | ModifyDirection.LEFT)

            if tl or br:
                self.video_widget.setCursor(Qt.SizeFDiagCursor)
            elif tr or bl:
                self.video_widget.setCursor(Qt.SizeBDiagCursor)
            elif self._mouse_mode in (ModifyDirection.LEFT,  ModifyDirection.RIGHT):
                self.video_widget.setCursor(Qt.SizeHorCursor)
            elif self._mouse_mode in (ModifyDirection.TOP,  ModifyDirection.BOTTOM):
                self.video_widget.setCursor(Qt.SizeVerCursor)
            else:
                self.video_widget.setCursor(Qt.SizeAllCursor)

        self.video_widget.update()

    def render(self, painter: QPainter, time_in_recording: int) -> None:
        if self.recording is None:
            return

        eye_frame = self.recording.eye.sample([time_in_recording])[0]
        if abs(time_in_recording - eye_frame.time) / 1e9 > 1 / 30:
            return

        image = qimage_from_frame(eye_frame.gray).scaled(
            int(eye_frame.width * self._scale),
            int(eye_frame.height * self._scale)
        )
        painter.setOpacity(self._opacity)

        if self._border_width > 0:
            pen = painter.pen()
            pen.setWidth(self._border_width)
            pen.setColor(self._border_color)
            painter.setPen(pen)
            painter.drawRect(self.get_rect().adjusted(
                -self._border_width / 2,
                -self._border_width / 2,
                self._border_width / 2,
                self._border_width / 2,
            ))

        painter.drawImage(
            QPointF(
                self._offset_x * self.recording.scene.width,
                self._offset_y * self.recording.scene.height
            ),
            image,
        )

        if self._mouse_mode != ModifyDirection(0):
            pen = painter.pen()
            pen.setWidth(7)
            pen.setColor("#6D7BE0")
            painter.setPen(pen)
            painter.setBrush(Qt.GlobalColor.transparent)
            painter.drawRect(self.get_rect().adjusted(0, 0, -1, -1))

        painter.setOpacity(1.0)

    def get_rect(self) -> QRectF:
        return QRectF(
            self._offset_x * self.recording.scene.width,
            self._offset_y * self.recording.scene.height,
            int(self._scale * self.recording.eye.width),
            int(self._scale * self.recording.eye.height)
        )

    @property
    @property_params(widget=None)
    def offset_x(self) -> float:
        return self._offset_x

    @offset_x.setter
    def offset_x(self, value: float) -> None:
        self._offset_x = value

    @property
    @property_params(widget=None)
    def offset_y(self) -> float:
        return self._offset_y

    @offset_y.setter
    def offset_y(self, value: float) -> None:
        self._offset_y = value

    @property
    @property_params(widget=None)
    def scale(self) -> float:
        return self._scale

    @scale.setter
    def scale(self, value: float) -> None:
        self._scale = value

    @property
    @property_params(min=0, max=1, step=0.01, decimals=3)
    def opacity(self) -> float:
        return self._opacity

    @opacity.setter
    def opacity(self, value: float) -> None:
        self._opacity = value

    @property
    @property_params(min=0, max=100)
    def border_width(self) -> int:
        return self._border_width

    @border_width.setter
    def border_width(self, value: int) -> None:
        self._border_width = value

    @property
    def border_color(self) -> QColor:
        return self._border_color

    @border_color.setter
    def border_color(self, value: QColor) -> None:
        self._border_color = value