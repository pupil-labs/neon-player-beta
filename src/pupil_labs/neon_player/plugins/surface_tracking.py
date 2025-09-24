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
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from qt_property_widgets.utilities import PersistentPropertiesMixin, property_params
from surface_tracker import (
    CornerId,
    Marker,
    SurfaceLocation,
    SurfaceTracker,
)

from pupil_labs import neon_player
from pupil_labs.neon_player import Plugin, ProgressUpdate, action
from pupil_labs.neon_player.plugins.gaze import CrosshairViz, GazeVisualization
from pupil_labs.neon_player.ui.video_render_widget import VideoRenderWidget
from pupil_labs.neon_player.utilities import qimage_from_frame


class SurfaceTrackingPlugin(Plugin):
    label = "Surface Tracking"

    def __init__(self) -> None:
        super().__init__()
        self.marker_cache_file = self.get_cache_path() / "markers.npy"
        self.surface_cache_file = self.get_cache_path() / "surfaces.npy"

        self.marker_color = QColor("#22ff22")

        self.markers_by_frame: list[list[Marker]] = []
        self.surface_locations: dict[str, list[SurfaceLocation]] = {}
        self.tracker = SurfaceTracker()

        self._surfaces: list["TrackedSurface"] = []
        self._jobs = []

        self.timer = QTimer()
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._update_surface_locations)

    def _update_surface_locations(self) -> None:
        frame_idx = self.get_scene_idx_for_time()
        markers = self.markers_by_frame[frame_idx]
        for surface in self._surfaces:
            if surface.tracker_surface is None:
                continue

            surface.location = self.tracker.locate_surface(
                surface.tracker_surface,
                markers
            )

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        self.camera = Radial_Dist_Camera(
            name='Scene',
            resolution=(recording.scene.width, recording.scene.height),
            K=self.recording.calibration.scene_camera_matrix,
            D=self.recording.calibration.scene_distortion_coefficients,
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
        painter.setBrush(self.marker_color)
        painter.setPen(self.marker_color)
        painter.setOpacity(0.85)

        frame_idx = self.get_scene_idx_for_time(time_in_recording)
        if frame_idx < 0:
            return

        scene_frame = self.recording.scene.sample([time_in_recording])[0]
        if abs(time_in_recording - scene_frame.time) / 1e9 > 1 / 30:
            return

        if frame_idx < len(self.markers_by_frame):
            for marker in self.markers_by_frame[frame_idx]:
                corners = np.array(marker.vertices())
                self._paint_distorted_polygon(painter, corners)

        painter.setOpacity(1.0)

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

            anchors = self.tracker.locate_surface_visual_anchors(
                surface.tracker_surface,
                location
            )
            self._paint_distorted_polygon(painter, anchors.perimeter_polyline)

    def _paint_distorted_polygon(self, painter: QPainter, points, resolution=10) -> None:
        points = insert_interpolated_points(points, resolution)
        points = self.camera.distort_points_on_image_plane(points).reshape(-1, 2)

        points = [QPointF(*point) for point in points]
        painter.drawPolygon(points)

    def _load_marker_cache(self) -> None:
        self.markers_by_frame = np.load(self.marker_cache_file, allow_pickle=True)
        self.attempt_surface_locations_load()
        self.changed.emit()

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
    def surfaces(self) -> list["TrackedSurface"]:
        return self._surfaces

    @surfaces.setter
    def surfaces(self, value: list["TrackedSurface"]):
        new_surfaces = [
            surface for surface in value if surface not in self._surfaces
        ]
        removed_surfaces = [
            surface for surface in self._surfaces if surface not in value
        ]
        self._surfaces = value

        frame_idx = self.get_scene_idx_for_time()
        for surface in new_surfaces:
            if surface.uid == "":
                surface.uid = str(uuid.uuid4())

            surface.changed.connect(self.changed.emit)

            locations_path = self.get_cache_path() / f"{surface.uid}_locations.npy"
            if locations_path.exists():
                self._load_surface_locations_cache(surface.uid)
            elif not self.app.headless:
                job = self.job_manager.run_background_action(
                    f"Detect Surface Locations [{surface.name}]",
                    "SurfaceTrackingPlugin.bg_detect_surface_locations",
                    surface.uid,
                    frame_idx,
                )
                job.finished.connect(
                    lambda: self._load_surface_locations_cache(surface.uid)
                )
                self._jobs.append(job)

        for surface in removed_surfaces:
            locations_path = self.get_cache_path() / f"{surface.uid}_locations.npy"
            if locations_path.exists():
                locations_path.unlink()

            surf_path = self.get_cache_path() / f"{surface.uid}_surface.pkl"
            if surf_path.exists():
                surf_path.unlink()

        self.changed.emit()

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
            scene_image = frame.gray
            #@TODO: apply brightness/contrast adjustments

            markers = [
                self.apriltag_to_surface_marker(m) for m in detector.detect(scene_image)
            ]
            markers_by_frame.append(markers)

            yield ProgressUpdate((frame_idx + 1) / len(self.recording.scene))

        # save the makers_by_frame to the cache file
        self.marker_cache_file.parent.mkdir(parents=True, exist_ok=True)
        with self.marker_cache_file.open("wb") as f:
            np.save(f, np.array(markers_by_frame, dtype=object))

    def bg_detect_surface_locations(
        self,
        uid: str,
        starting_frame_idx: int,
    ) -> T.Generator[ProgressUpdate, None, None]:

        if starting_frame_idx >= len(self.markers_by_frame):
            logging.error("Marker detection not yet complete")
            return

        markers = self.markers_by_frame[starting_frame_idx]
        tracker_surf = self.tracker.define_surface(uid, markers)
        locations = []
        for frame_idx, markers in enumerate(self.markers_by_frame):
            location = self.tracker.locate_surface(tracker_surf, markers)

            locations.append(location)

            yield ProgressUpdate((frame_idx + 1) / len(self.markers_by_frame))

        # save the makers_by_frame to the cache file
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
        # Construct the surface tracker marker UID
        # Extract vertices in the correct format form apriltag marker
        vertices = [[point] for point in apriltag_marker.corners]
        vertices = self.camera.undistort_points_on_image_plane(vertices)

        starting_with = CornerId.TOP_LEFT
        clockwise = True

        return Marker.from_vertices(
            uid=apriltag_marker.tag_id,
            undistorted_image_space_vertices=vertices,
            starting_with=starting_with,
            clockwise=clockwise,
        )


class TrackedSurface(PersistentPropertiesMixin, QObject):
    changed = Signal()
    surface_location_changed = Signal()
    view_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._uid = ""
        self._name = ""
        self._markers = []
        self._outline_color: QColor = QColor(255, 0, 255, 128)
        self._outline_width: float = 3
        self.tracker_surface = None

        self._render_size = QSize(400, 400)
        self._location = None

        self._visualizations: list[GazeVisualization] = [
            CrosshairViz(),
        ]
        self.preview_widget = None

    @property
    @property_params(dont_encode=True, widget=None)
    def location(self) -> SurfaceLocation|None:
        return self._location

    @location.setter
    def location(self, value: SurfaceLocation|None) -> None:
        self._location = value
        self.surface_location_changed.emit()

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

    @action
    def view(self) -> None:
        self.preview_widget = SurfaceViewWidget(self)
        self.preview_widget.show()

        width = min(1024, max(self._render_size.width(), 400))
        aspect = self._render_size.width() / self._render_size.height()
        self.preview_widget.resize(width, width / aspect)

    @property
    @property_params(use_subclass_selector=True, add_button_text="Add visualization")
    def visualizations(self) -> list["GazeVisualization"]:
        return self._visualizations

    @visualizations.setter
    def visualizations(self, value: list["GazeVisualization"]) -> None:
        self._visualizations = value

        for viz in self._visualizations:
            viz.changed.connect(self.changed.emit)


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

        tracker_plugin = Plugin.get_instance_by_name("SurfaceTrackingPlugin")
        self.tracker = tracker_plugin.tracker
        self.camera = tracker_plugin.camera
        self.gaze_plugin = Plugin.get_instance_by_name("GazeDataPlugin")

        self.refit_rect()

    def refit_rect(self) -> None:
        self.fit_rect(QSize(self.surface.render_width, self.surface.render_height))

    def paintEvent(self, event: QPaintEvent) -> None:
        if self.surface.location is None:
            painter = QPainter(self)
            painter.fillRect(0, 0, self.width(), self.height(), Qt.GlobalColor.gray)
            return

        app = neon_player.instance()
        scene_frame = app.recording.scene.sample([app.current_ts])[0]

        # these are in undisorted, cropped image space
        corners_in_image = np.array(self.tracker.surface_points_in_image_space(
            self.surface.tracker_surface,
            self.surface.location,
            np.array([(0, 1.0), (1.0, 1.0), (1.0, 0), (0, 0)], dtype=np.float32),
        ))

        corners_in_optimal = self.camera.map_points_to_optimal_matrix(corners_in_image)
        undistorted_image = self.camera.undistort_image(scene_frame.bgr, use_optimal=True)

        width = self.surface._render_size.width()
        height = self.surface._render_size.height()
        dst_pts = np.array([
            [0, 0],
            [width - 1, 0],
            [width - 1, height - 1],
            [0, height - 1]
        ], dtype=np.float32)

        homography, _ = cv2.findHomography(corners_in_optimal, dst_pts)

        surface_image = cv2.warpPerspective(
            undistorted_image,
            homography,
            np.int32([width, height])
        )

        painter = QPainter(self)
        painter.fillRect(0, 0, self.width(), self.height(), Qt.GlobalColor.black)
        self.transform_painter(painter)
        painter.drawImage(0, 0, qimage_from_frame(surface_image))

        gazes = self.gaze_plugin.get_gazes_for_scene().point
        offset_gazes = gazes + np.array([
            self.gaze_plugin.offset_x * scene_frame.width,
            self.gaze_plugin.offset_y * scene_frame.height
        ])

        gazes = self.distorted_scene_to_undistorted_surface(gazes, homography)
        offset_gazes = self.distorted_scene_to_undistorted_surface(offset_gazes, homography)

        for viz in self.surface.visualizations:
            viz.render(
                painter,
                offset_gazes if viz.use_offset else gazes,
            )

    def distorted_scene_to_undistorted_surface(
        self,
        points: npt.NDArray[np.float64],
        homography: npt.NDArray,
    ) -> None:
        points = self.camera.undistort_points_on_image_plane(points, use_optimal=True)
        points = points[:, np.newaxis, :]
        return cv2.perspectiveTransform(points, homography).reshape(-1, 2)


class Radial_Dist_Camera:
    def __init__(
        self,
        name: str,
        resolution: tuple[int, int],
        K: npt.ArrayLike,
        D: npt.ArrayLike,
    ) -> None:
        self.name = name
        self.resolution = resolution
        self.K: npt.NDArray[np.float64] = np.array(K)
        self.D: npt.NDArray[np.float64] = np.array(D)

        self.optimal_K, _ = cv2.getOptimalNewCameraMatrix(
            self.K,
            self.D,
            self.resolution,
            alpha=0.0,
            newImgSize=self.resolution
        )

    @property
    def focal_length(self) -> float:
        fx = self.K[0, 0]
        fy = self.K[1, 1]

        return (fx + fy) / 2

    def undistort_points_on_image_plane(
        self, points: npt.NDArray[np.float64], use_optimal: bool = False
    ) -> npt.NDArray[np.float64]:
        points = self.unprojectPoints(points, use_distortion=True, use_optimal=False)
        points = self.projectPoints(points, use_distortion=False, use_optimal=use_optimal)

        return points

    def distort_points_on_image_plane(
        self, points: npt.NDArray[np.float64], use_optimal: bool = False
    ) -> npt.NDArray[np.float64]:
        points = self.unprojectPoints(
            points,
            use_distortion=False,
            use_optimal=use_optimal
        )
        return self.projectPoints(
            points,
            use_distortion=True,
            use_optimal=use_optimal
        )

    def map_points_to_optimal_matrix(
        self, points: npt.NDArray[np.float64], use_distortion: bool = False
    ):
        points = self.unprojectPoints(
            points,
            use_distortion=use_distortion,
            use_optimal=False
        )
        return self.projectPoints(
            points,
            use_distortion=use_distortion,
            use_optimal=True
        )

    def map_points_from_optimal_matrix(
        self, points: npt.NDArray[np.float64], use_distortion: bool = False
    ):
        points = self.unprojectPoints(
            points,
            use_distortion=use_distortion,
            use_optimal=True
        )
        return self.projectPoints(
            points,
            use_distortion=use_distortion,
            use_optimal=False
        )

    def unprojectPoints(
        self,
        pts_2d: npt.NDArray,
        use_distortion: bool = True,
        normalize: bool = False,
        use_optimal: bool = False
    ) -> npt.NDArray:
        """Undistorts points according to the camera model.
        :param pts_2d, shape: Nx2
        :return: Array of unprojected 3d points, shape: Nx3
        """
        pts_2d = np.array(pts_2d, dtype=np.float32)

        # Delete any posibly wrong 3rd dimension
        if pts_2d.ndim == 1 or pts_2d.ndim == 3:
            pts_2d = pts_2d.reshape((-1, 2))

        # Add third dimension the way cv2 wants it
        if pts_2d.ndim == 2:
            pts_2d = pts_2d.reshape((-1, 1, 2))

        _D = self.D if use_distortion else np.asarray([[0.0, 0.0, 0.0, 0.0, 0.0]])

        pts_2d_undist = cv2.undistortPoints(
            pts_2d,
            self.K,
            _D,
            self.optimal_K if use_optimal else self.K,
        )

        pts_3d = cv2.convertPointsToHomogeneous(pts_2d_undist)
        pts_3d.shape = -1, 3

        if normalize:
            pts_3d /= np.linalg.norm(pts_3d, axis=1)[:, np.newaxis]

        return pts_3d

    def projectPoints(
        self,
        object_points: npt.NDArray,
        rvec: npt.NDArray|None =None,
        tvec: npt.NDArray|None =None,
        use_distortion: bool = True,
        use_optimal: bool = False
    ) -> npt.NDArray:
        """Projects a set of points onto the camera plane as defined by the camera model.
        :param object_points: Set of 3D world points
        :param rvec: Set of vectors describing the rotation of the camera when recording
            the corresponding object point
        :param tvec: Set of vectors describing the translation of the camera when
            recording the corresponding object point
        :return: Projected 2D points
        """
        input_dim = object_points.ndim

        object_points = object_points.reshape((1, -1, 3))

        if rvec is None:
            rvec = np.zeros(3).reshape(1, 1, 3)
        else:
            rvec = np.array(rvec).reshape(1, 1, 3)

        if tvec is None:
            tvec = np.zeros(3).reshape(1, 1, 3)
        else:
            tvec = np.array(tvec).reshape(1, 1, 3)

        _D = self.D if use_distortion else np.asarray([[0.0, 0.0, 0.0, 0.0, 0.0]])

        image_points, _ = cv2.projectPoints(
            object_points,
            rvec,
            tvec,
            self.optimal_K if use_optimal else self.K,
            _D
        )

        if input_dim == 2:
            image_points.shape = (-1, 2)
        elif input_dim == 3:
            image_points.shape = (-1, 1, 2)
        return image_points

    def undistort_image(
        self,
        img: npt.NDArray,
        use_optimal: bool = False
    ) -> npt.NDArray:
        return cv2.undistort(
            img,
            self.K,
            self.D,
            None,
            self.optimal_K if use_optimal else self.K
        )


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
