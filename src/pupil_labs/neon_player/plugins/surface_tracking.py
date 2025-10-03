import logging
import pickle
import typing as T
import uuid

import cv2
import numpy as np
import numpy.typing as npt
import pupil_apriltags
from pupil_labs.neon_recording import NeonRecording
from PySide6.QtCore import QObject, QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QMouseEvent, QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import QMessageBox, QPushButton, QWidget
from qt_property_widgets.utilities import PersistentPropertiesMixin, property_params
from surface_tracker import (
    Camera,
    CornerId,
    Marker,
    SurfaceLocation,
    SurfaceTracker,
)
from surface_tracker import (
    surface as surface_module,
)

from pupil_labs import neon_player
from pupil_labs.neon_player import Plugin, ProgressUpdate, action
from pupil_labs.neon_player.plugins.gaze import CrosshairViz, GazeVisualization
from pupil_labs.neon_player.ui.video_render_widget import VideoRenderWidget
from pupil_labs.neon_player.utilities import qimage_from_frame

# this function seems to return vertices in reverse order
__src_bounding_quadrangle = surface_module._bounding_quadrangle
def __patched_bounding_quadrangle(*args, **kwargs):
    v = __src_bounding_quadrangle(*args, **kwargs)
    return v[[3, 2, 1, 0]]

surface_module._bounding_quadrangle = __patched_bounding_quadrangle


class SurfaceTrackingPlugin(Plugin):
    label = "Surface Tracking"

    def __init__(self) -> None:
        super().__init__()
        self.marker_cache_file = self.get_cache_path() / "markers.npy"
        self.surface_cache_file = self.get_cache_path() / "surfaces.npy"

        self._marker_color = QColor("#22ff22")
        self._marker_color.setAlpha(200)

        self.markers_by_frame: list[list[Marker]] = []
        self.surface_locations: dict[str, list[SurfaceLocation]] = {}
        self.tracker = SurfaceTracker()

        self._surfaces: list["TrackedSurface"] = []
        self._jobs = []
        self._surface_locator_jobs = {}

        self.timer = QTimer()
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._update_displays)

        self.marker_edit_widgets = {}

    def _update_displays(self) -> None:
        frame_idx = self.get_scene_idx_for_time()
        if frame_idx >= len(self.markers_by_frame):
            return

        if self.is_time_gray():
            for marker_widget in self.marker_edit_widgets.values():
                marker_widget.hide()

            for surface in self._surfaces:
                surface.location = None
                if surface.edit_markers:
                    for handle_widget in surface.handle_widgets.values():
                        handle_widget.hide()

            return

        markers = self.markers_by_frame[frame_idx]
        for surface in self._surfaces:
            if surface.tracker_surface is None:
                continue

            surface.location = self.tracker.locate_surface(
                surface.tracker_surface,
                markers
            )

        # if we're editing a surface's markers
        if any(s.edit_markers for s in self._surfaces):
            self._update_editing_markers()

    def _update_editing_markers(self):
        frame_idx = self.get_scene_idx_for_time()
        markers = self.markers_by_frame[frame_idx]
        present_markers = {m.uid: m for m in markers}
        vrw = self.app.main_window.video_widget
        edit_surface = next((s for s in self._surfaces if s.edit_markers), None)
        if edit_surface is not None and edit_surface.location is None:
            for marker_widget in self.marker_edit_widgets.values():
                marker_widget.hide()
            return

        for marker_uid, marker_widget in self.marker_edit_widgets.items():
            if marker_uid not in present_markers:
                marker_widget.hide()
            else:
                marker_widget.show()
                marker = present_markers[marker_uid]
                undistorted_center = np.mean(marker.vertices(), axis=0)
                distorted_center = self.camera.distort_points(
                    [undistorted_center]
                )[0]

                vrw.set_child_scaled_center(
                    marker_widget,
                    distorted_center[0],
                    distorted_center[1]
                )

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        self.camera = OptimalCamera(
            self.recording.calibration.scene_camera_matrix,
            self.recording.calibration.scene_distortion_coefficients,
            (recording.scene.width, recording.scene.height),
        )
        self.attempt_marker_cache_load()
        self.timer.start()

    def attempt_marker_cache_load(self) -> None:
        if self.marker_cache_file.exists():
            self._load_marker_cache()
            return

        else:
            if self.app.headless:
                if self.marker_cache_file.exists():
                    self._load_marker_cache()

            else:
                self.marker_detection_job = self.job_manager.run_background_action(
                    "Detect Markers", "SurfaceTrackingPlugin.bg_detect_markers"
                )
                self.marker_detection_job.finished.connect(self._load_marker_cache)

    def attempt_surface_locations_load(self) -> None:
        for surface in self.surfaces:
            self._load_surface_locations_cache(surface.uid)

    def render(self, painter: QPainter, time_in_recording: int) -> None:
        frame_idx = self.get_scene_idx_for_time(time_in_recording)
        if frame_idx < 0:
            return

        scene_frame = self.recording.scene.sample([time_in_recording])[0]
        if abs(time_in_recording - scene_frame.time) / 1e9 > 1 / 30:
            return

        # Render markers
        painter.setBrush(self._marker_color)
        painter.setPen(self._marker_color)
        if frame_idx < len(self.markers_by_frame):
            for marker in self.markers_by_frame[frame_idx]:
                corners = np.array(marker.vertices())
                self._distort_and_paint_polygon(painter, corners)

        painter.setOpacity(1.0)

        font = painter.font()
        font.setPointSize(24)
        font.setBold(True)
        painter.setFont(font)

        default_transform = painter.transform()
        for surface in self.surfaces:
            if surface.uid not in self.surface_locations:
                continue

            locations = self.surface_locations[surface.uid]
            location = locations[frame_idx]
            if not location:
                continue

            if surface.tracker_surface is None:
                continue

            p = painter.pen()
            p.setColor(surface.outline_color)
            p.setWidth(surface.outline_width)
            painter.setPen(p)
            painter.setBrush(QColor("#00000000"))

            anchors = self.tracker.surface_corner_positions_in_image_space(
                surface.tracker_surface,
                location,
                CornerId.all_corners()
            )
            anchors = np.array(list(anchors.values()))

            self._distort_and_paint_polygon(painter, anchors)

            top_edge = anchors[1] - anchors[0]

            # Compute angle with respect to the x‑axis
            angle_rad = np.arctan2(top_edge[1], top_edge[0])
            top_middle = top_edge / 2.0 + anchors[0]
            top_middle_distorted = self.camera.distort_points([top_middle]).flatten()
            painter.translate(QPointF(*top_middle_distorted))
            painter.rotate(np.degrees(angle_rad))
            painter.translate(QPointF(-15, -5))

            painter.drawText(0, 0, "Top")
            painter.setTransform(default_transform)

    def _distort_and_paint_polygon(self, painter: QPainter, points, resolution=10) -> None:
        points = insert_interpolated_points(points, resolution)
        points = self.camera.distort_points(points)

        points = [QPointF(*point) for point in points]
        painter.drawPolygon(points)

    def _load_marker_cache(self) -> None:
        self.markers_by_frame = np.load(self.marker_cache_file, allow_pickle=True)
        self.attempt_surface_locations_load()
        self.changed.emit()
        for frame_markers in self.markers_by_frame:
            for marker in frame_markers:
                if marker.uid not in self.marker_edit_widgets:
                    widget = MarkerEditWidget(marker.uid)
                    widget.setParent(self.app.main_window.video_widget)
                    self.marker_edit_widgets[marker.uid] = widget

    def _load_surface_locations_cache(self, surface_uid: str) -> None:
        surface = self.get_surface(surface_uid)
        surf_path = self.get_cache_path() / f"{surface_uid}_surface.pkl"
        if surf_path.exists():
            with surf_path.open("rb") as f:
                surface.tracker_surface = pickle.load(f)

        locations_path = self.get_cache_path() / f"{surface_uid}_locations.npy"
        if locations_path.exists():
            data = np.load(locations_path, allow_pickle=True)
            self.surface_locations[surface_uid] = data

            self.changed.emit()

    @property
    def marker_color(self) -> QColor:
        return self._marker_color

    @marker_color.setter
    def marker_color(self, value: QColor) -> None:
        self._marker_color = value

    @property
    def surfaces(self) -> list["TrackedSurface"]:
        return self._surfaces

    @surfaces.setter
    def surfaces(self, value: list["TrackedSurface"]):
        frame_idx = self.get_scene_idx_for_time()
        new_surfaces = [
            surface for surface in value if surface not in self._surfaces
        ]
        removed_surfaces = [
            surface for surface in self._surfaces if surface not in value
        ]

        fresh_surfaces = [s for s in new_surfaces if s.uid == ""]
        if len(fresh_surfaces) > 0:
            frame_detect_done = frame_idx < len(self.markers_by_frame)
            if not frame_detect_done or len(self.markers_by_frame[frame_idx]) < 1:
                QMessageBox.warning(self.app.main_window, "No markers detected", "Markers must be visible and detected on the current frame to add a new surface.")
                for surface in new_surfaces:
                    value.remove(surface)

                new_surfaces = []

        self._surfaces = value

        for surface in new_surfaces:
            if surface.uid == "":
                surface.uid = str(uuid.uuid4())

            surface.changed.connect(self.changed.emit)
            surface.marker_edit_changed.connect(
                lambda s=surface: self.on_marker_edit_changed(s)
            )
            surface.locations_invalidated.connect(
                lambda s=surface:self.on_locations_invalidated(s)
            )

            locations_path = self.get_cache_path() / f"{surface.uid}_locations.npy"
            if locations_path.exists():
                self._load_surface_locations_cache(surface.uid)

            elif not self.app.headless:
                self._start_bg_surface_locator(surface, frame_idx)

        for surface in removed_surfaces:
            surface.cleanup_widgets()
            locations_path = self.get_cache_path() / f"{surface.uid}_locations.npy"
            if locations_path.exists():
                locations_path.unlink()

            surf_path = self.get_cache_path() / f"{surface.uid}_surface.pkl"
            if surf_path.exists():
                surf_path.unlink()

        self.changed.emit()

    def on_marker_edit_changed(self, surface: "TrackedSurface") -> None:
        if surface.edit_markers:
            for other_surface in self.surfaces:
                if other_surface != surface:
                    other_surface.edit_markers = False

            self.marker_editing_surface = surface
            for w in self.marker_edit_widgets.values():
                w.set_surface(surface)

        else:
            self.marker_editing_surface = None
            for w in self.marker_edit_widgets.values():
                w.hide()

    def on_locations_invalidated(self, surface: "TrackedSurface") -> None:
        surf_path = self.get_cache_path() / f"{surface.uid}_surface.pkl"
        with surf_path.open("wb") as f:
            pickle.dump(surface.tracker_surface, f)

        self._start_bg_surface_locator(surface)

    def _start_bg_surface_locator(self, surface: "TrackedSurface", *args, **kwargs):
        if surface.uid in self._surface_locator_jobs:
            self._surface_locator_jobs[surface.uid].cancel()

        job = self.job_manager.run_background_action(
            f"Detect Surface Locations [{surface.name}]",
            "SurfaceTrackingPlugin.bg_detect_surface_locations",
            surface.uid,
            *args,
            **kwargs
        )
        job.finished.connect(
            lambda: self._load_surface_locations_cache(surface.uid)
        )
        self._surface_locator_jobs[surface.uid] = job

    def get_surface(self, uid: str):
        for s in self._surfaces:
            if s.uid == uid:
                return s

    def bg_detect_markers(self) -> T.Generator[ProgressUpdate, None, None]:
        logging.info("Detecting markers...")
        detector = pupil_apriltags.Detector(
            families="tag36h11", nthreads=2, quad_decimate=2.0, decode_sharpening=1.0
        )

        markers_by_frame = []
        for frame_idx, frame in enumerate(self.recording.scene):
            #@TODO: apply brightness/contrast adjustments
            scene_image = self.camera.undistort_image(frame.gray)

            markers = [
                self.apriltag_to_surface_marker(m) for m in detector.detect(scene_image)
            ]
            markers_by_frame.append(markers)

            yield ProgressUpdate((frame_idx + 1) / len(self.recording.scene))

        self.marker_cache_file.parent.mkdir(parents=True, exist_ok=True)
        with self.marker_cache_file.open("wb") as f:
            np.save(f, np.array(markers_by_frame, dtype=object))

    def bg_detect_surface_locations(
        self,
        uid: str,
        starting_frame_idx: int = -1,
    ) -> T.Generator[ProgressUpdate, None, None]:
        if starting_frame_idx >= len(self.markers_by_frame):
            logging.error("Marker detection not yet complete")
            return

        if starting_frame_idx < 0:
            # load surface from disk
            surf_path = self.get_cache_path() / f"{uid}_surface.pkl"
            if surf_path.exists():
                with surf_path.open("rb") as f:
                    tracker_surf = pickle.load(f)

        else:
            markers = self.markers_by_frame[starting_frame_idx]
            tracker_surf = self.tracker.define_surface(uid, markers)

        locations = []
        for frame_idx, markers in enumerate(self.markers_by_frame):
            location = self.tracker.locate_surface(tracker_surf, markers)

            locations.append(location)

            yield ProgressUpdate((frame_idx + 1) / len(self.markers_by_frame))

        locations_path = self.get_cache_path() / f"{uid}_locations.npy"
        locations_path.parent.mkdir(parents=True, exist_ok=True)
        with locations_path.open("wb") as f:
            np.save(f, np.array(locations, dtype=object))

        surf_path = self.get_cache_path() / f"{uid}_surface.pkl"
        with surf_path.open("wb") as f:
            pickle.dump(tracker_surf, f)

    def apriltag_to_surface_marker(
        self,
        apriltag_marker: pupil_apriltags.Detection
    ) -> Marker:
        return Marker.from_vertices(
            uid=apriltag_marker.tag_id,
            undistorted_image_space_vertices=apriltag_marker.corners,
            starting_with=CornerId.BOTTOM_LEFT,
            clockwise=False,
        )


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


class TrackedSurface(PersistentPropertiesMixin, QObject):
    changed = Signal()
    locations_invalidated = Signal()
    surface_location_changed = Signal()
    view_requested = Signal(object)
    marker_edit_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._uid = ""
        self._name = "[Unnamed surface]"
        self._markers = []
        self._outline_color: QColor = QColor(255, 0, 255, 255)
        self._outline_width: float = 3
        self._can_edit_corners = False
        self._can_edit_markers = False
        self.tracker_surface = None

        self._render_size = QSize(400, 400)
        self._location = None

        self._visualizations: list[GazeVisualization] = [
            CrosshairViz(),
        ]
        self.preview_widget = None
        self.handle_widgets = {}
        self.corner_positions = {}

    def __del__(self):
        self.cleanup_widgets()

    def to_dict(self) -> dict[str, T.Any]:
        state = super().to_dict()
        state["edit_markers"] = False
        state["edit_corners"] = False
        return state

    def cleanup_widgets(self):
        for hw in self.handle_widgets.values():
            hw.setParent(None)
            hw.deleteLater()

        self.handle_widgets = {}

    def add_marker(self, marker_uid: str) -> None:
        frame_idx = self.tracker_plugin.get_scene_idx_for_time()
        markers = self.tracker_plugin.markers_by_frame[frame_idx]
        marker = next((m for m in markers if m.uid == marker_uid), None)

        self.tracker.add_markers_to_surface(
            self.tracker_surface,
            self.location,
            [marker],
        )
        self.locations_invalidated.emit()

    def remove_marker(self, marker_uid: str) -> None:
        self.tracker.remove_markers_from_surface(
            self.tracker_surface,
            self.location,
            [marker_uid],
        )
        self.locations_invalidated.emit()

    @property
    @property_params(dont_encode=True, widget=None)
    def location(self) -> SurfaceLocation|None:
        return self._location

    @location.setter
    def location(self, value: SurfaceLocation|None) -> None:
        if self._location is not None and value is not None:
            if np.all(value.transform_matrix_from_image_to_surface_undistorted == self._location.transform_matrix_from_image_to_surface_undistorted):
                return

        self._location = value
        self.surface_location_changed.emit()
        self.update_handle_positions()

    def update_handle_positions(self):
        if self._location is None:
            for w in self.handle_widgets.values():
                w.hide()
            return

        for w in self.handle_widgets.values():
            w.show()

        tracker_plugin = Plugin.get_instance_by_name("SurfaceTrackingPlugin")
        camera = tracker_plugin.camera
        tracker = tracker_plugin.tracker
        app = neon_player.instance()
        vrw = app.main_window.video_widget

        undistorted_corners = np.array(tracker.surface_points_in_image_space(
            self.tracker_surface,
            self._location,
            np.array([c.value for c in CornerId.all_corners()], dtype=np.float32),
        ))

        distorted_corners = camera.distort_points(undistorted_corners)

        for w, undistorted_corner, distorted_corner, corner_id in zip(
            self.handle_widgets.values(),
            undistorted_corners,
            distorted_corners,
            CornerId.all_corners(),
            strict=False
        ):
            self.corner_positions[corner_id] = undistorted_corner
            vrw.set_child_scaled_center(w, distorted_corner[0], distorted_corner[1])
            w.show()

    @property
    def edit_corners(self) -> bool:
        return self._can_edit_corners

    @edit_corners.setter
    def edit_corners(self, value: bool) -> None:
        self._can_edit_corners = value
        if not value:
            self.cleanup_widgets()

        else:
            app = neon_player.instance()
            vrw = app.main_window.video_widget
            self.handle_widgets = {
                CornerId.TOP_LEFT: SurfaceHandle(),
                CornerId.TOP_RIGHT: SurfaceHandle(),
                CornerId.BOTTOM_RIGHT: SurfaceHandle(),
                CornerId.BOTTOM_LEFT: SurfaceHandle(),
            }

            for corner_id, w in self.handle_widgets.items():
                w.setFixedSize(25, 25)
                w.setParent(vrw)
                w.position_changed.connect(
                    lambda pos, corner=corner_id: self.on_corner_changed(corner, pos)
                )

            self.update_handle_positions()

    def on_corner_changed(self, corner_id: CornerId, pos: QPointF) -> None:
        camera = Plugin.get_instance_by_name("SurfaceTrackingPlugin").camera

        pos = np.array([pos.x(), pos.y()])
        undistorted_corner = camera.undistort_points(pos)
        self.corner_positions[corner_id] = undistorted_corner.flatten()
        tracker_plugin = Plugin.get_instance_by_name("SurfaceTrackingPlugin")
        tracker = tracker_plugin.tracker

        tracker.move_surface_corner_positions_in_image_space(
            self.tracker_surface,
            self.location,
            self.corner_positions
        )
        self.locations_invalidated.emit()

    @property
    def edit_markers(self) -> bool:
        return self._can_edit_markers

    @edit_markers.setter
    def edit_markers(self, value: bool) -> None:
        self._can_edit_markers = value
        self.marker_edit_changed.emit()

    @property
    @property_params(widget=None)
    def uid(self) -> str:
        return self._uid

    @uid.setter
    def uid(self, value: str):
        self._uid = value

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, name: str) -> None:
        self._name = name

    @property
    def outline_color(self) -> QColor:
        return self._outline_color

    @outline_color.setter
    def outline_color(self, outline_color: QColor) -> None:
        self._outline_color = outline_color

    @property
    @property_params(min=0, max=100)
    def outline_width(self) -> float:
        return self._outline_width

    @outline_width.setter
    def outline_width(self, value: float) -> None:
        self._outline_width = value

    @property
    @property_params(min=1, max=2560)
    def render_width(self) -> int:
        return self._render_size.width()

    @render_width.setter
    def render_width(self, value: int) -> None:
        self._render_size.setWidth(value)

    @property
    @property_params(min=1, max=2560)
    def render_height(self) -> int:
        return self._render_size.height()

    @render_height.setter
    def render_height(self, value: int) -> None:
        self._render_size.setHeight(value)

    @property
    @property_params(use_subclass_selector=True, add_button_text="Add visualization")
    def visualizations(self) -> list["GazeVisualization"]:
        return self._visualizations

    @visualizations.setter
    def visualizations(self, value: list["GazeVisualization"]) -> None:
        self._visualizations = value

        for viz in self._visualizations:
            viz.changed.connect(self.changed.emit)

    @action
    def view_surface(self) -> None:
        self.preview_widget = SurfaceViewWidget(self)
        self.preview_widget.show()

        width = min(1024, max(self._render_size.width(), 400))
        aspect = self._render_size.width() / self._render_size.height()
        self.preview_widget.resize(width, width / aspect)

    @property
    @property_params(widget=None, dont_encode=True)
    def tracker_plugin(self) -> SurfaceTrackingPlugin:
        return Plugin.get_instance_by_name("SurfaceTrackingPlugin")

    @property
    @property_params(widget=None, dont_encode=True)
    def tracker(self) -> SurfaceTracker:
        return self.tracker_plugin.tracker

    def image_points_to_surface(self, points):
        undistorted_points = self.tracker_plugin.camera.undistort_points(points)
        return cv2.perspectiveTransform(
            undistorted_points.reshape(-1, 1, 2),
            self.location.transform_matrix_from_image_to_surface_undistorted
        ).reshape(-1, 2)


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
        surface: TrackedSurface,
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


class OptimalCamera(Camera):
    def __init__(
        self,
        camera_matrix: npt.ArrayLike,
        distortion_coefficients: npt.ArrayLike,
        resolution: tuple[int, int],
    ) -> None:
        super().__init__(camera_matrix, distortion_coefficients)
        self.resolution = resolution

        self.optimal_matrix, _ = cv2.getOptimalNewCameraMatrix(
            self.camera_matrix,
            self.distortion_coefficients,
            self.resolution,
            alpha=1.0,
            newImgSize=self.resolution
        )

        self.undistortion_maps = cv2.initUndistortRectifyMap(
            self.camera_matrix,
            self.distortion_coefficients,
            None,
            self.optimal_matrix,
            self.resolution,
            cv2.CV_32FC1
        )

        self.distortion_maps = self._build_distort_maps()

    def _build_distort_maps(self):
        w_dst, h_dst = self.resolution

        # create grid of pixel coordinates in the distorted image
        xs = np.arange(w_dst)
        ys = np.arange(h_dst)
        xv, yv = np.meshgrid(xs, ys)
        pix = np.stack((xv, yv), axis=-1).astype(np.float32)  # (h_dst, w_dst, 2)

        # Convert pixel coords (u_d, v_d) in distorted image to normalized camera coords x_d = K^{-1} * [u;v;1]
        K = np.asarray(self.camera_matrix, dtype=np.float64)
        pts = pix.reshape(-1, 1, 2).astype(np.float64)

        undistorted_pts = cv2.undistortPoints(pts, K, self.distortion_coefficients, R=None, P=self.optimal_matrix)  # returns (N,1,2) in pixel coords of undistorted image when P provided

        # undistorted_pts are pixel coordinates in the undistorted image corresponding to each distorted pixel.
        map_xy = undistorted_pts.reshape(h_dst, w_dst, 2).astype(np.float32)

        return map_xy[..., 0], map_xy[..., 1]

    def undistort_points(self, points: npt.ArrayLike):
        return self._map_points(points, self.distortion_maps)

    def distort_points(self, points: npt.ArrayLike):
        return self._map_points(points, self.undistortion_maps)

    def _map_points(self, points, maps):
        points = np.asarray(points).reshape(-1, 2)
        ix = np.clip(np.round(points[:, 0]).astype(int), 0, self.resolution[0] - 1)
        iy = np.clip(np.round(points[:, 1]).astype(int), 0, self.resolution[1] - 1)

        return np.stack((maps[0][iy, ix], maps[1][iy, ix]), axis=-1)

    def undistort_image(
        self,
        img: npt.NDArray,
    ) -> npt.NDArray:
        return cv2.remap(img, *self.undistortion_maps, interpolation=cv2.INTER_LINEAR)

    def distort_image(self, img):
        distorted_img = cv2.remap(img, *self.distortion_maps, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)

        return distorted_img


def insert_interpolated_points(points: npt.NDArray, n_between: int = 10) -> npt.NDArray:
    points = np.asarray(points, dtype=float)

    n_pts, dim = points.shape
    if n_pts < 2:
        return points.copy()

    t = np.linspace(0, 1, n_between + 2)[:, None]

    out_len = n_pts + (n_pts - 1) * n_between
    out = np.empty((out_len, dim), dtype=float)

    idx = 0
    for i in range(n_pts - 1):
        p0, p1 = points[i], points[i + 1]
        segment = (1 - t) * p0 + t * p1
        out[idx:idx + n_between + 1] = segment[:-1]
        idx += n_between + 1

    # Append the final original point
    out[-1] = points[-1]

    return out
