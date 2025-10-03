import cv2
import numpy as np
import numpy.typing as npt
from PySide6.QtCore import QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QMouseEvent, QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import QPushButton, QWidget
from surface_tracker import Camera

from pupil_labs import neon_player
from pupil_labs.neon_player import Plugin
from pupil_labs.neon_player.ui.video_render_widget import VideoRenderWidget
from pupil_labs.neon_player.utilities import qimage_from_frame


class MarkerEditWidget(QPushButton):
    def __init__(self, marker_uid: str) -> None:
        super().__init__()
        self.setCheckable(True)
        self.marker_uid = marker_uid
        self.surface = None

        icon = QIcon()
        icon.addPixmap(
            QPixmap(neon_player.asset_path("add.svg")),
            QIcon.Normal,
            QIcon.Off
        )
        icon.addPixmap(
            QPixmap(neon_player.asset_path("remove.svg")),
            QIcon.Normal,
            QIcon.On
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
        self.setChecked(self.marker_uid in surface.tracker_surface.registered_marker_uids)
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

    def __init__(self):
        super().__init__()
        self.moved = False
        self.position_changed_debounce_timer = QTimer()
        self.position_changed_debounce_timer.setInterval(1000)
        self.position_changed_debounce_timer.setSingleShot(True)
        self.position_changed_debounce_timer.timeout.connect(self.emit_new_position)

        self.new_pos = None

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setPen("#ffff00")
        painter.setBrush("#ffff00")
        painter.setOpacity(0.5)
        painter.drawEllipse(0, 0, self.width() - 1, self.height() - 1)

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.moved = True
            vrw = self.parent()
            pos = self.mapToParent(event.pos())
            self.new_pos = vrw.map_point(pos)
            vrw.set_child_scaled_center(
                self,
                self.new_pos.x(),
                self.new_pos.y()
            )

    def mouseReleaseEvent(self, event: QMouseEvent):
        if not (event.buttons() & Qt.MouseButton.LeftButton) and self.moved:
            self.position_changed_debounce_timer.start()

        self.moved = False

    def emit_new_position(self):
        self.position_changed.emit(self.new_pos)


class SurfaceViewWidget(VideoRenderWidget):
    def __init__(
        self,
        surface: "TrackedSurface",
        *args,
        **kwargs
    ) -> None:
        super().__init__(*args, **kwargs)

        self.surface = surface
        self.surface.changed.connect(self.refit_rect)
        self.surface.surface_location_changed.connect(self.update)

        self.tracker_plugin = Plugin.get_instance_by_name("SurfaceTrackingPlugin")
        self.tracker = self.tracker_plugin.tracker
        self.camera = self.tracker_plugin.camera
        self.gaze_plugin = Plugin.get_instance_by_name("GazeDataPlugin")

        self.refit_rect()

    def refit_rect(self) -> None:
        self.fit_rect(QSize(self.surface.render_width, self.surface.render_height))

    def paintEvent(self, event: QPaintEvent) -> None:
        if self.tracker_plugin.is_time_gray() or self.surface.location is None:
            painter = QPainter(self)
            painter.fillRect(0, 0, self.width(), self.height(), Qt.GlobalColor.gray)
            return

        app = neon_player.instance()
        scene_frame = app.recording.scene.sample([app.current_ts])[0]
        undistorted_image = self.camera.undistort_image(scene_frame.bgr)

        dst_size = (self.surface._render_size.width(), self.surface._render_size.height())
        S = np.float64([
            [dst_size[0], 0.0,   0.0],
            [0.0,   dst_size[1], 0.0],
            [0.0,   0.0,   1.0]
        ])
        h_scaled = S @ self.surface.location.transform_matrix_from_image_to_surface_undistorted

        surface_image = cv2.warpPerspective(undistorted_image, h_scaled, dst_size)

        painter = QPainter(self)
        painter.fillRect(0, 0, self.width(), self.height(), Qt.GlobalColor.black)
        self.transform_painter(painter)
        painter.drawImage(0, 0, qimage_from_frame(surface_image))

        gazes = self.gaze_plugin.get_gazes_for_scene().point
        offset_gazes = gazes + np.array([
            self.gaze_plugin.offset_x * scene_frame.width,
            self.gaze_plugin.offset_y * scene_frame.height
        ])

        gazes = self.surface.image_points_to_surface(gazes)
        gazes[:, 0] *= self.surface.render_width
        gazes[:, 1] *= self.surface.render_height
        offset_gazes = gazes

        for viz in self.surface.visualizations:
            viz.render(
                painter,
                offset_gazes if viz.use_offset else gazes,
            )
