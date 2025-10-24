import logging
import pickle
import typing as T
import uuid
from pathlib import Path

import av
import cv2
import numpy as np
import numpy.typing as npt
import pupil_apriltags
import pupil_labs.video as plv
from pupil_labs.neon_recording import NeonRecording
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QMessageBox
from surface_tracker import (
    Camera,
    CornerId,
    Marker,
    SurfaceLocation,
    SurfaceTracker,
)

from pupil_labs import neon_player
from pupil_labs.neon_player import Plugin, ProgressUpdate, action
from pupil_labs.neon_player.utilities import (
    SlotDebouncer,
    ndarray_from_qimage,
    qimage_from_frame,
)

from .tracked_surface import TrackedSurface
from .ui import MarkerEditWidget


class SurfaceTrackingPlugin(Plugin):
    label = "Surface Tracking"

    def __init__(self) -> None:
        super().__init__()
        self.marker_cache_file = self.get_cache_path() / "markers.npy"
        self.surface_cache_file = self.get_cache_path() / "surfaces.npy"

        self._marker_color = QColor("#22ff22")
        self._marker_color.setAlpha(200)
        self._render_overlays_in_export = False

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

    def on_disabled(self) -> None:
        self.get_timeline().remove_timeline_plot("Visible markers")

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

        for surface in self._surfaces:
            if surface.tracker_surface is None:
                continue

            surface.location = self.surface_locations[surface.uid][frame_idx]

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

    def render(self, painter: QPainter, time_in_recording: int) -> None:
        if not self._render_overlays_in_export:
            exporter = Plugin.get_instance_by_name("VideoExporter")
            if exporter is not None and exporter.is_exporting:
                return

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

            if surface.heatmap_alpha > 0.0 and surface._heatmap is not None:
                export_window = self.app.recording_settings.export_window
                if export_window[0] <= time_in_recording <= export_window[1]:
                    scalar = np.float64([
                        [1 / surface._heatmap.shape[1], 0.0,   0.0],
                        [0.0,   1 / surface._heatmap.shape[0], 0.0],
                        [0.0,   0.0,   1.0]
                    ])

                    h_scaled = location.transform_matrix_from_surface_to_image_undistorted @ scalar
                    scene_size = self.recording.scene.width, self.recording.scene.height

                    rgb_heatmap = cv2.applyColorMap(surface._heatmap, surface.heatmap_color.value)
                    rgb_heatmap = cv2.cvtColor(rgb_heatmap, cv2.COLOR_BGR2RGB)
                    undistorted_heatmap = cv2.warpPerspective(
                        rgb_heatmap,
                        h_scaled,
                        scene_size,
                    )
                    undistorted_mask = cv2.warpPerspective(
                        255 * np.ones((surface._heatmap.shape[0], surface._heatmap.shape[1]), dtype='uint8'),
                        h_scaled,
                        scene_size,
                    )

                    distorted_heatmap = self.camera.distort_image(undistorted_heatmap)

                    distorted_mask = self.camera.distort_image(undistorted_mask)
                    distorted_heatmap_rgba = np.dstack((distorted_heatmap, distorted_mask))

                    painter.setOpacity(surface.heatmap_alpha)
                    painter.drawImage(
                        0, 0,
                        qimage_from_frame(distorted_heatmap_rgba)
                    )
                    painter.setOpacity(1.0)

            p = painter.pen()
            p.setColor(surface.outline_color)
            p.setWidth(surface.outline_width)
            painter.setPen(p)
            painter.setBrush(QColor("#00000000"))

            if surface.edit_corners:
                vrw = self.app.main_window.video_widget
                points = [
                    vrw.map_point(w.geometry().center())
                    for w in surface.handle_widgets.values()
                ]
                anchors = np.array([ (p.x(), p.y()) for p in points ])
                anchors = self.camera.undistort_points(anchors)

                p.setStyle(Qt.PenStyle.DashLine)
                p.setDashPattern([1, 4])
                painter.setPen(p)

                self._distort_and_paint_polygon(painter, anchors)

                p.setStyle(Qt.PenStyle.SolidLine)
                painter.setPen(p)

            else:
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
        self.trigger_scene_update()
        for frame_markers in self.markers_by_frame:
            for marker in frame_markers:
                if marker.uid not in self.marker_edit_widgets:
                    widget = MarkerEditWidget(marker.uid)
                    widget.setParent(self.app.main_window.video_widget)
                    widget.hide()
                    self.marker_edit_widgets[marker.uid] = widget

        # marker visibility plot
        marker_count_by_frame = [len(v) for v in self.markers_by_frame]
        marker_count_changes = []
        for frame_idx, value in enumerate(marker_count_by_frame):
            t = self.recording.scene[frame_idx].time
            if len(marker_count_changes) == 0:
                marker_count_changes.append((t, value))
            elif marker_count_changes[-1][1] != value:
                marker_count_changes.append((
                    t - 1,
                    marker_count_changes[-1][1]
                ))
                marker_count_changes.append((
                    t,
                    value
                ))

        self.get_timeline().add_timeline_plot(
            "Visible markers",
            marker_count_changes
        )

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

            self.trigger_scene_update()

        self.attempt_load_surface_heatmap(surface_uid)

    def attempt_load_surface_heatmap(self, surface_uid):
        cache_file = self.get_cache_path() / f"{surface_uid}_heatmap.png"
        if cache_file.exists():
            self._load_surface_heatmap(surface_uid)
            return

        else:
            if self.app.headless:
                if cache_file.exists():
                    self._load_surface_heatmap(surface_uid)

            else:
                surface = self.get_surface(surface_uid)
                heatmap_job = self.job_manager.run_background_action(
                    f"Build Surface Heatmap [{surface.name}]",
                    "SurfaceTrackingPlugin.bg_build_heatmap",
                    surface_uid
                )
                heatmap_job.finished.connect(
                    lambda: self._load_surface_heatmap(surface_uid)
                )

    def bg_build_heatmap(self, surface_uid: str) -> T.Generator[ProgressUpdate, None, None]:
        surface = self.get_surface(surface_uid)

        start_time, stop_time = neon_player.instance().recording_settings.export_window
        start_mask = self.recording.scene.time >= start_time
        stop_mask = self.recording.scene.time <= stop_time
        scene_frames = self.recording.scene[start_mask & stop_mask]

        mapped_gazes = np.empty((0, 2), dtype=np.float32)
        for idx, frame in enumerate(scene_frames):
            location = self.surface_locations[surface_uid][frame.index]
            if not location:
                continue

            surface.location = location

            start_time = frame.time
            if frame.index < len(self.recording.scene) - 1:
                stop_time = self.recording.scene[frame.index + 1].time
            else:
                stop_time = start_time + 1e9 / 30

            start_mask = self.recording.gaze.time >= start_time
            stop_mask = self.recording.gaze.time <= stop_time

            gazes = self.recording.gaze[start_mask & stop_mask]
            if len(gazes) > 0:
                mapped_gazes = np.append(
                    mapped_gazes,
                    surface.apply_offset_and_map_gazes(gazes),
                    axis=0
                )

            yield ProgressUpdate((1 + idx) / len(scene_frames))

        lower_pass = np.all(mapped_gazes >= 0.0, axis=1)
        upper_pass = np.all(mapped_gazes <= 1.0, axis=1)
        surface_gazes = mapped_gazes[lower_pass & upper_pass]

        val = 3 * (1 - surface._heatmap_smoothness)
        blur_factor = max((1 - val), 0)
        res_exponent = max(val, 0.35)
        resolution = int(10**res_exponent)

        aspect_ratio = surface.preview_options.width / surface.preview_options.height

        grid = (
            int(resolution),
            max(1, int(resolution * aspect_ratio)),
        )

        xvals, yvals = surface_gazes[:, 0], surface_gazes[:, 1]

        hist, *_ = np.histogram2d(
            yvals, xvals, bins=grid, range=[[0, 1.0], [0, 1.0]], density=False
        )
        filter_h = 19 + blur_factor * 15
        filter_w = filter_h * aspect_ratio
        filter_h = int(filter_h) // 2 * 2 + 1
        filter_w = int(filter_w) // 2 * 2 + 1

        hist = cv2.GaussianBlur(hist, (filter_h, filter_w), 0)
        hist_max = hist.max()
        hist *= (255.0 / hist_max) if hist_max else 0.0
        hist = hist.astype(np.uint8)

        cache_file = self.get_cache_path() / f"{surface.uid}_heatmap.png"
        cv2.imwrite(str(cache_file), hist)

    def _load_surface_heatmap(self, surface_uid: str) -> None:
        surface = self.get_surface(surface_uid)
        cache_file = self.get_cache_path() / f"{surface_uid}_heatmap.png"
        surface._heatmap = cv2.imread(str(cache_file))
        self.trigger_scene_update()

    def recalculate_heatmap(self, surface_uid: str) -> None:
        cache_file = self.get_cache_path() / f"{surface_uid}_heatmap.png"
        if cache_file.exists():
            cache_file.unlink()

        self.get_surface(surface_uid)._heatmap = None
        self.trigger_scene_update()

        self.attempt_load_surface_heatmap(surface_uid)

    @property
    def marker_color(self) -> QColor:
        return self._marker_color

    @marker_color.setter
    def marker_color(self, value: QColor) -> None:
        self._marker_color = value

    @property
    def render_overlays_in_export(self) -> bool:
        return self._render_overlays_in_export

    @render_overlays_in_export.setter
    def render_overlays_in_export(self, value: bool) -> None:
        self._render_overlays_in_export = value

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

            surface_counter = 1
            while surface.name == "":
                candidate_name = f"Surface {surface_counter}"
                if candidate_name not in [s.name for s in self._surfaces]:
                    surface.name = candidate_name
                surface_counter += 1

            surface.changed.connect(self.changed.emit)
            SlotDebouncer.debounce(
                surface.heatmap_invalidated,
                surface.recalculate_heatmap,
            )
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
            if surface.edit_markers:
                for marker_widget in self.marker_edit_widgets.values():
                    marker_widget.hide()

            surface.cleanup_widgets()
            locations_path = self.get_cache_path() / f"{surface.uid}_locations.npy"
            if locations_path.exists():
                locations_path.unlink()

            surf_path = self.get_cache_path() / f"{surface.uid}_surface.pkl"
            if surf_path.exists():
                surf_path.unlink()

            heatmap_path = self.get_cache_path() / f"{surface.uid}_heatmap.png"
            if heatmap_path.exists():
                heatmap_path.unlink()

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

        surface._heatmap = None
        self.trigger_scene_update()

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

    def bg_export_surface_video(
        self,
        destination: Path,
        uid: str
    ) -> T.Generator[ProgressUpdate, None, None]:
        surface = self.get_surface(uid)

        start_time, stop_time = neon_player.instance().recording_settings.export_window
        start_mask = self.recording.scene.time >= start_time
        stop_mask = self.recording.scene.time <= stop_time
        scene_frames = self.recording.scene[start_mask & stop_mask]

        with plv.Writer(destination / f"{surface.name}_surface_view.mp4") as writer:
            for output_idx, scene_frame in enumerate(scene_frames):
                if scene_frame.index < len(self.surface_locations[uid]):
                    rel_ts = (scene_frame.time - self.recording.scene.time[0]) / 1e9
                    frame = QImage(
                        surface.preview_options._render_size,
                        QImage.Format.Format_BGR888
                    )
                    painter = QPainter(frame)
                    surface.location = self.surface_locations[uid][scene_frame.index]
                    surface.render(painter, scene_frame.time)
                    painter.end()

                    frame_pixels = ndarray_from_qimage(frame)
                    av_frame = av.VideoFrame.from_ndarray(frame_pixels, format="bgr24")

                    plv_frame = plv.VideoFrame(av_frame, rel_ts, output_idx, "")
                    writer.write_frame(plv_frame)

                yield ProgressUpdate((output_idx + 1) / len(scene_frames))

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

    @action
    def export(self, destination: Path = Path()) -> None:
        start_time, stop_time = neon_player.instance().recording_settings.export_window
        start_mask = self.recording.gaze.time >= start_time
        stop_mask = self.recording.gaze.time <= stop_time

        gazes_in_window = self.recording.gaze[start_mask & stop_mask]

        for surface in self._surfaces:
            surface.export_gazes(gazes_in_window, destination)
            try:
                surface.export_fixations(gazes_in_window, destination)
            except:
                logging.warning("Failed to export surface fixations. Is the fixation plugin enabled?")


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
            alpha=0.0,
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
