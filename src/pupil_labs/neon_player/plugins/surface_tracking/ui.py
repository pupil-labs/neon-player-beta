
import cv2
import numpy as np
from PySide6.QtCore import QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QMouseEvent, QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import QPushButton, QSplitter, QWidget
from qt_property_widgets.widgets import PropertyForm
from surface_tracker import CornerId

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

    def __init__(self, surface, corner_id: CornerId):
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
            CornerId.TOP_LEFT: 0,
            CornerId.TOP_RIGHT: 270,
            CornerId.BOTTOM_RIGHT: 180,
            CornerId.BOTTOM_LEFT: 90,
        }

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setPen(self.surface.outline_color)
        painter.setBrush(self.surface.outline_color)
        painter.setOpacity(0.5)

        painter.drawPie(
            0, 0,
            self.width() - 1, self.height() - 1,
            self.starting_angles[self.corner_id] * 16,
            270 * 16
        )

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.moved = True
            pos = self.mapToParent(event.pos())
            self.new_pos = self.parent().map_point(pos)
            self.parent().set_child_scaled_center(
                self,
                self.new_pos.x(),
                self.new_pos.y()
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
        self.tracker = self.tracker_plugin.tracker
        self.camera = self.tracker_plugin.camera
        self.gaze_plugin = Plugin.get_instance_by_name("GazeDataPlugin")

        self.refit_rect()

    def refit_rect(self) -> None:
        self.fit_rect(QSize(
            self.surface.preview_options.width,
            self.surface.preview_options.height
        ))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        if self.tracker_plugin.is_time_gray() or self.surface.location is None:
            painter = QPainter(self)
            painter.fillRect(0, 0, self.width(), self.height(), Qt.GlobalColor.gray)
            return

        app = neon_player.instance()
        scene_frame = app.recording.scene.sample([app.current_ts])[0]
        undistorted_image = self.camera.undistort_image(scene_frame.bgr)

        dst_size = (
            self.surface.preview_options.width,
            self.surface.preview_options.height
        )
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

        mapped_gazes = self.surface.image_points_to_surface(gazes)
        mapped_gazes[:, 0] *= self.surface.preview_options.width
        mapped_gazes[:, 1] *= self.surface.preview_options.height
        offset_gazes = None

        aggregations = {}
        offset_aggregations = {}
        for viz in self.surface.preview_options.visualizations:
            if viz.use_offset:
                if offset_gazes is None:
                    offset_gazes = gazes + np.array([
                        self.gaze_plugin.offset_x * scene_frame.width,
                        self.gaze_plugin.offset_y * scene_frame.height
                    ])
                    mapped_offset_gazes = self.surface.image_points_to_surface(offset_gazes)
                    mapped_offset_gazes[:, 0] *= self.surface.preview_options.width
                    mapped_offset_gazes[:, 1] *= self.surface.preview_options.height
                    if viz._aggregation not in offset_aggregations:
                        offset_aggregations[viz._aggregation] = viz._aggregation.apply(
                            mapped_offset_gazes
                        )
            elif viz._aggregation not in aggregations:
                aggregations[viz._aggregation] = viz._aggregation.apply(mapped_gazes)

            aggregation_dict = offset_aggregations if viz.use_offset else aggregations
            viz.render(
                painter,
                aggregation_dict[viz._aggregation]
            )


class SurfaceViewWindow(QSplitter):
    def __init__(self, surface: "TrackedSurface") -> None:
        super().__init__()

        self.view_widget = SurfaceViewWidget(surface)
        self.view_widget.setMinimumWidth(400)
        self.addWidget(self.view_widget)

        self.options_widget = PropertyForm(surface.preview_options)
        self.options_widget.layout().setContentsMargins(5, 5, 5, 5)
        self.addWidget(self.options_widget)

        surface.preview_options.changed.connect(surface.changed.emit)
        surface.changed.connect(self.view_widget.refit_rect)

        Plugin.get_instance_by_name("GazeDataPlugin").changed.connect(self.view_widget.refit_rect)
