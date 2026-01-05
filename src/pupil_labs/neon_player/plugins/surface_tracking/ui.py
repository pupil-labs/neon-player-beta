from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QMouseEvent, QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import QPushButton, QSplitter, QVBoxLayout, QWidget
from qt_property_widgets.widgets import PropertyForm

from pupil_labs import neon_player
from pupil_labs.neon_player import Plugin
from pupil_labs.neon_player.ui.video_render_widget import VideoRenderWidget

if TYPE_CHECKING:
    from pupil_labs.neon_player.plugins.surface_tracking.tracked_surface import (
        TrackedSurface,
    )


class MarkerEditWidget(QPushButton):
    def __init__(self, marker_uid: str) -> None:
        super().__init__()
        self.setCheckable(True)
        self.marker_uid = marker_uid
        self.surface = None

        icon = QIcon()
        icon.addPixmap(
            QPixmap(neon_player.asset_path("add.svg")), QIcon.Normal, QIcon.Off
        )
        icon.addPixmap(
            QPixmap(neon_player.asset_path("remove.svg")), QIcon.Normal, QIcon.On
        )
        self.setIcon(icon)
        self.setIconSize(QSize(24, 24))

        self.setStyleSheet("""
            QPushButton {
                border: none;
                background: transparent;
                padding: 0px;
            }
        """)

        self.setCursor(Qt.PointingHandCursor)

        self.clicked.connect(self.on_clicked)

    def set_surface(self, surface: "TrackedSurface") -> None:
        self.surface = surface
        self.setChecked(
            self.marker_uid in surface.tracker_surface.markers.keys()
        )
        self._update_tooltip(self.isChecked())

    def _update_tooltip(self, checked: bool) -> None:
        surface_name = self.surface.name or "Unnamed surface"
        if checked:
            self.setToolTip(f"Remove Marker ID {self.marker_uid} from {surface_name}")
        else:
            self.setToolTip(f"Add Marker ID {self.marker_uid} to {surface_name}")

    def on_clicked(self) -> None:
        if self.isChecked():
            self.surface.add_marker(self.marker_uid)
        else:
            self.surface.remove_marker(self.marker_uid)


class SurfaceHandle(QWidget):
    position_changed = Signal(QPointF)

    def __init__(self, surface, corner_id):
        super().__init__()
        self.surface = surface
        self.corner_id = corner_id
        self.moved = False
        self.position_changed_debounce_timer = QTimer()
        self.position_changed_debounce_timer.setInterval(1000)
        self.position_changed_debounce_timer.setSingleShot(True)
        self.position_changed_debounce_timer.timeout.connect(self.emit_new_position)

        self.new_pos = None
        self.scene_pos = np.array([0.0, 0.0])
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.starting_angles = {
            (0, 0): 0,
            (1, 0): 270,
            (1, 1): 180,
            (0, 1): 90,
        }

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        pen = painter.pen()
        pen.setColor("#039be5")
        pen.setWidth(3)
        painter.setPen(pen)
        painter.setBrush("#fff")
        painter.drawEllipse(3, 3, self.width() - 4, self.height() - 4)

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.moved = True
            pos = self.mapToParent(event.pos())
            self.new_pos = self.parent().map_point(pos)
            self.parent().set_child_scaled_center(
                self, self.new_pos.x(), self.new_pos.y()
            )
            self.setCursor(Qt.CursorShape.BlankCursor)

        neon_player.instance().main_window.video_widget.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if not (event.buttons() & Qt.MouseButton.LeftButton) and self.moved:
            self.position_changed_debounce_timer.start()
            self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.moved = False

    def set_scene_pos(self, scene_pos: np.ndarray):
        self.scene_pos = scene_pos
        self.parent().set_child_scaled_center(self, *scene_pos)
        self.show()

    def emit_new_position(self):
        self.position_changed.emit(self.new_pos)


class SurfaceViewWidget(VideoRenderWidget):
    def __init__(
        self,
        surface: "TrackedSurface",
    ) -> None:
        super().__init__()

        self.surface = surface
        self.surface.changed.connect(self.refit_rect)
        self.surface.surface_location_changed.connect(self.update)

        self.tracker_plugin = Plugin.get_instance_by_name("SurfaceTrackingPlugin")

        self.refit_rect()

    def refit_rect(self) -> None:
        self.fit_rect(QSize(*self.surface.preview_options.render_size))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        if self.tracker_plugin.is_time_gray() or self.surface.location is None:
            painter.fillRect(0, 0, self.width(), self.height(), Qt.GlobalColor.gray)
            return

        painter.fillRect(0, 0, self.width(), self.height(), Qt.GlobalColor.black)
        self.transform_painter(painter)
        self.surface.render(painter, neon_player.instance().current_ts)


class SurfaceViewWindow(QSplitter):
    def __init__(self, surface: "TrackedSurface") -> None:
        super().__init__()

        self.view_widget = SurfaceViewWidget(surface)
        self.view_widget.setMinimumWidth(400)
        self.addWidget(self.view_widget)

        self.options_widget = PropertyForm(surface.preview_options)
        self.options_widget.layout().setContentsMargins(5, 5, 5, 5)
        self.options_container = QWidget()
        self.options_container_layout = QVBoxLayout()
        self.options_container.setLayout(self.options_container_layout)
        self.options_container_layout.addWidget(self.options_widget)
        self.options_container_layout.addStretch()

        self.addWidget(self.options_container)

        surface.preview_options.changed.connect(surface.changed.emit)
        surface.changed.connect(self.view_widget.refit_rect)

        Plugin.get_instance_by_name("GazeDataPlugin").changed.connect(
            self.view_widget.refit_rect
        )
