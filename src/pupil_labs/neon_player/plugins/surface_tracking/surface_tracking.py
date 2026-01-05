import logging
import pickle
import typing as T
import uuid
from itertools import starmap
from pathlib import Path

import av
import cv2
import numpy as np
import numpy.typing as npt
import pupil_apriltags
import pupil_labs.video as plv
from pupil_labs.camera import Camera, perspective_transform
from pupil_labs.marker_mapper import Surface, utils
from pupil_labs.marker_mapper.surface import normalized_corners
from pupil_labs.neon_recording import NeonRecording
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (
    QColor,
    QColorConstants,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QMessageBox
from qt_property_widgets.utilities import action_params, property_params

from pupil_labs import neon_player
from pupil_labs.neon_player import Plugin, ProgressUpdate, action
from pupil_labs.neon_player.ui import ListPropertyAppenderAction
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

        self._draw_marker_ids = False
        self._draw_names = True
        self._export_overlays = False

        self.markers_by_frame: list[list] = []
        self.surface_locations: dict[str, list] = {}

        self._surfaces: list[TrackedSurface] = []

        self.marker_edit_widgets = {}
        self.header_action = ListPropertyAppenderAction("surfaces", "+ Add surface")

    def on_disabled(self) -> None:
        self.get_timeline().remove_timeline_plot("Marker visibility")
        for surface in self.surfaces:
            self.get_timeline().remove_timeline_plot(f"Surface: {surface.name}")
            self.get_timeline().remove_timeline_plot(f"Surface Gaze: {surface.name}")

    def _update_displays(self) -> None:
        frame_idx = self.get_scene_idx_for_time()
        if frame_idx >= len(self.markers_by_frame):
            return

        if self.is_time_gray():
            for marker_widget in self.marker_edit_widgets.values():
                marker_widget.hide()

            for surface in self._surfaces:
                surface.location = None
                if surface.edit:
                    for handle_widget in surface.handle_widgets.values():
                        handle_widget.hide()

            return

        for surface in self._surfaces:
            if surface.tracker_surface is None:
                continue

            surface.location = self.surface_locations[surface.uid][frame_idx]

        # if we're editing a surface's markers
        if any(s.edit for s in self._surfaces):
            self._update_editing_markers()

    def _update_editing_markers(self) -> None:
        frame_idx = self.get_scene_idx_for_time()
        markers = self.markers_by_frame[frame_idx]
        present_markers = {m.tag_id: m for m in markers}
        vrw = self.app.main_window.video_widget
        edit_surface = next((s for s in self._surfaces if s.edit), None)
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
                distorted_center = np.mean(marker.corners, axis=0)

                vrw.set_child_scaled_center(
                    marker_widget, distorted_center[0], distorted_center[1]
                )

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        self.camera = Camera(
            recording.scene.width,
            recording.scene.height,
            self.recording.calibration.scene_camera_matrix,
            self.recording.calibration.scene_distortion_coefficients,
        )
        self.attempt_marker_cache_load()

    def attempt_marker_cache_load(self) -> None:
        if self.marker_cache_file.exists():
            self._load_marker_cache()
            return

        if self.app.headless:
            if self.marker_cache_file.exists():
                self._load_marker_cache()

        else:
            self.marker_detection_job = self.job_manager.run_background_action(
                "Detect Markers", "SurfaceTrackingPlugin.bg_detect_markers"
            )
            self.marker_detection_job.finished.connect(self._load_marker_cache)

    def render(self, painter: QPainter, time_in_recording: int) -> None:  # noqa: C901
        self._update_displays()
        if not self._export_overlays:
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
        font = painter.font()
        font.setBold(True)
        font.setPointSize(24)
        painter.setFont(font)
        if frame_idx < len(self.markers_by_frame):
            for marker in self.markers_by_frame[frame_idx]:
                self._distort_and_draw_marker(painter, marker.corners, marker.tag_id)

        for surface in self.surfaces:
            if surface.uid not in self.surface_locations:
                continue

            locations = self.surface_locations[surface.uid]
            location = locations[frame_idx]
            if not location:
                continue

            if surface.tracker_surface is None:
                continue

            show_heatmap = surface.show_heatmap and surface.heatmap_alpha > 0.0
            if show_heatmap and surface._heatmap is not None:
                export_window = self.app.recording_settings.export_window
                if export_window[0] <= time_in_recording <= export_window[1]:
                    scalar = np.float64([
                        [1 / surface._heatmap.shape[1], 0.0, 0.0],
                        [0.0, 1 / surface._heatmap.shape[0], 0.0],
                        [0.0, 0.0, 1.0],
                    ])

                    heatmap_to_scene = location[1] @ scalar
                    scene_size = self.recording.scene.width, self.recording.scene.height

                    rgb_heatmap = cv2.applyColorMap(
                        surface._heatmap, surface.heatmap_color.value
                    )
                    rgb_heatmap = cv2.cvtColor(rgb_heatmap, cv2.COLOR_BGR2RGB)
                    undistorted_heatmap = cv2.warpPerspective(
                        rgb_heatmap,
                        heatmap_to_scene,
                        scene_size,
                    )
                    undistorted_mask = cv2.warpPerspective(
                        255
                        * np.ones(
                            (surface._heatmap.shape[0], surface._heatmap.shape[1]),
                            dtype="uint8",
                        ),
                        heatmap_to_scene,
                        scene_size,
                    )

                    # @TODO: use optimal matrix to have less edge truncation
                    distorted_heatmap = self.camera.distort_image(undistorted_heatmap)
                    distorted_mask = self.camera.distort_image(undistorted_mask)
                    distorted_heatmap_rgba = np.dstack((
                        distorted_heatmap,
                        distorted_mask,
                    ))

                    painter.setOpacity(surface.heatmap_alpha)
                    painter.drawImage(0, 0, qimage_from_frame(distorted_heatmap_rgba))
                    painter.setOpacity(1.0)

            anchors = None
            if surface.edit and surface.handle_widgets:
                try:
                    vrw = self.app.main_window.video_widget
                    points = [
                        vrw.scaled_children_positions[w]
                        for w in surface.handle_widgets.values()
                    ]
                    anchors = np.array([[p[0], p[1]] for p in points])
                    anchors = self.camera.undistort_points(anchors)
                except KeyError:
                    pass

            if anchors is None:
                if not surface.location:
                    return
                anchors = perspective_transform(
                    normalized_corners(),
                    surface.location[1],
                )

            points = self._distort_and_trace_surface(painter, anchors)

            if self._draw_names:
                old_pen = painter.pen()
                old_brush = painter.brush()

                painter.setBrush(QColor("#000"))
                pen = QPen(QColor("white"))
                pen.setWidthF(5.0)
                pen.setJoinStyle(Qt.RoundJoin)

                path = QPainterPath()
                painter.setPen(pen)
                center = np.mean(points[0:-1], axis=0)
                text_rect = painter.fontMetrics().boundingRect(surface.name)
                path.addText(
                    int(center[0] - text_rect.width() / 2),
                    int(center[1] + text_rect.height() / 2) - 8,
                    painter.font(),
                    surface.name,
                )

                painter.drawPath(path)
                painter.setPen(Qt.NoPen)
                painter.drawPath(path)

                painter.setPen(old_pen)
                painter.setBrush(old_brush)

    def _distort_and_trace_surface(
        self,
        painter: QPainter,
        anchors,
        resolution=10,
    ) -> np.ndarray:
        points = insert_interpolated_points(anchors, resolution)
        points = self.camera.distort_points(points)

        pen = painter.pen()
        pen.setWidth(5)
        pen.setColor("#039be5")
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)

        qpoints = list(starmap(QPointF, points))
        for seg_idx in [1, 2, 3, 0]:
            if seg_idx == 0:
                pen.setColor("#ff0000")
                painter.setPen(pen)

            start_idx = seg_idx * (resolution + 1)
            end_idx = start_idx + resolution + 2

            painter.drawPolyline(qpoints[start_idx:end_idx])

        return points

    def _distort_and_draw_marker(
        self,
        painter: QPainter,
        points,
        marker_id,
        resolution=10,
    ) -> None:
        marker_id = str(marker_id)

        if resolution > 0:
            points = self.camera.undistort_points(points)
            points = insert_interpolated_points(points, resolution)
            points = self.camera.distort_points(points)

        color = QColor("#00ff00")

        pen = painter.pen()
        pen.setWidth(5)
        pen.setColor(color)
        painter.setPen(pen)

        color.setAlpha(200)
        painter.setBrush(color)
        painter.drawPolygon(list(starmap(QPointF, points)))

        if self._draw_marker_ids:
            old_pen = painter.pen()

            painter.setBrush("#000")
            pen = QPen(QColor("#fff"))
            pen.setWidthF(5.0)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)

            text_rect = painter.fontMetrics().boundingRect(marker_id)
            center = np.mean(points[0:-1], axis=0)

            path = QPainterPath()
            text_rect = painter.fontMetrics().boundingRect(marker_id)
            path.addText(
                int(center[0] - text_rect.width() / 2),
                int(center[1] + text_rect.height() / 2) - 8,
                painter.font(),
                marker_id,
            )
            painter.drawPath(path)
            painter.setPen(Qt.NoPen)
            painter.drawPath(path)

            painter.setPen(old_pen)

    def _load_marker_cache(self) -> None:
        self.markers_by_frame = np.load(self.marker_cache_file, allow_pickle=True)
        self.trigger_scene_update()
        for frame_markers in self.markers_by_frame:
            for marker in frame_markers:
                if marker.tag_id not in self.marker_edit_widgets:
                    widget = MarkerEditWidget(marker.tag_id)
                    widget.setParent(self.app.main_window.video_widget)
                    widget.hide()
                    self.marker_edit_widgets[marker.tag_id] = widget

        # marker visibility plot
        marker_count_by_frame = np.array(
            [len(v) for v in self.markers_by_frame], dtype=np.int32
        )
        change_indices = np.where(np.diff(marker_count_by_frame) != 0)[0]
        start_indices = np.concatenate(([0], change_indices + 1))
        stop_indices = np.concatenate((
            change_indices,
            [len(marker_count_by_frame) - 1],
        ))

        start_times = self.recording.scene.time[start_indices].tolist()
        stop_times = self.recording.scene.time[stop_indices].tolist()

        n_markers = marker_count_by_frame[start_indices].tolist()

        self.get_timeline().add_timeline_broken_bar(
            "Marker visibility",
            [
                (start, stop, n)
                for start, stop, n in zip(start_times, stop_times, n_markers)
                if n > 0
            ],
        )

    def _load_surface_locations_cache(self, surface_uid: str) -> None:
        surface = self.get_surface(surface_uid)
        surf_path = self.get_cache_path() / f"{surface_uid}_surface.pkl"
        if surf_path.exists():
            with surf_path.open("rb") as f:
                surface.tracker_surface = pickle.load(f)  # noqa: S301

        locations_path = self.get_cache_path() / f"{surface_uid}_locations.npy"
        if locations_path.exists():
            data = np.load(locations_path, allow_pickle=True)
            self.surface_locations[surface_uid] = data

            surface2image = data[surface.defining_frame_index][1]

            # set surface size
            image = utils.crop_image(
                np.zeros((1, 1, 3), np.uint8),
                surface2image,
                width=500,
                height=None,
            )

            w, h = image.shape[1], image.shape[0]
            if w % 2 != 0:
                w -= 1
            if h % 2 != 0:
                h -= 1

            surface.preview_options.render_size = [w, h]
            surface.changed.emit()

            self.add_visibility_timeline(surface)

            # refresh
            self.trigger_scene_update()

        self.attempt_load_surface_heatmap(surface_uid)

    def add_visibility_timeline(self, surface):
        surf_viz_path = self.get_cache_path() / f"{surface.uid}_surface_visibility.pkl"
        if not surf_viz_path.exists():
            return

        with surf_viz_path.open("rb") as f:
            visibilities = pickle.load(f)

        self.get_timeline().remove_timeline_plot(f"Surface: {surface.name}")
        self.get_timeline().add_timeline_broken_bar(
            f"Surface: {surface.name}", visibilities, color="#3273FF"
        )

    def add_surface_gaze_timeline(self, surface):
        gaze_upon_file = self.get_cache_path() / f"{surface.uid}_gazes.pkl"
        if not gaze_upon_file.exists():
            return

        self.get_timeline().remove_timeline_plot(f"Surface Gaze: {surface.name}")
        with open(gaze_upon_file, "rb") as f:
            self.get_timeline().add_timeline_broken_bar(
                f"Surface Gaze: {surface.name}", pickle.load(f), color="#73F7FF"
            )

    def attempt_load_surface_heatmap(self, surface_uid):
        cache_file = self.get_cache_path() / f"{surface_uid}_heatmap.png"
        if cache_file.exists():
            self._load_surface_heatmap(surface_uid)
            return

        if self.app.headless:
            if cache_file.exists():
                self._load_surface_heatmap(surface_uid)

        else:
            surface = self.get_surface(surface_uid)
            heatmap_job = self.job_manager.run_background_action(
                f"Build Surface Heatmap [{surface.name}]",
                "SurfaceTrackingPlugin.bg_build_heatmap",
                surface_uid,
            )
            surface.add_bg_job(heatmap_job)
            heatmap_job.finished.connect(
                lambda: self._load_surface_heatmap(surface_uid)
            )

    def bg_build_heatmap(
        self, surface_uid: str
    ) -> T.Generator[ProgressUpdate, None, None]:
        surface = self.get_surface(surface_uid)

        start_time, stop_time = neon_player.instance().recording_settings.export_window
        start_mask = self.recording.scene.time >= start_time
        stop_mask = self.recording.scene.time <= stop_time
        scene_frames = self.recording.scene[start_mask & stop_mask]

        mapped_gazes = np.empty((0, 2), dtype=np.float32)
        gaze_ons = np.zeros([len(self.recording.scene)], dtype=np.uint8)

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
                frame_gazes = surface.apply_offset_and_map_gazes(gazes)
                mapped_gazes = np.append(mapped_gazes, frame_gazes, axis=0)

                valid_rows = np.all((frame_gazes >= 0) & (frame_gazes <= 1), axis=1)
                gaze_ons[idx] = np.any(valid_rows)

            yield ProgressUpdate((1 + idx) / len(scene_frames))

        lower_pass = np.all(mapped_gazes >= 0.0, axis=1)
        upper_pass = np.all(mapped_gazes <= 1.0, axis=1)
        surface_gazes = mapped_gazes[lower_pass & upper_pass]

        val = 3 * (1 - surface._heatmap_smoothness)
        blur_factor = max((1 - val), 0)
        res_exponent = max(val, 0.35)
        resolution = int(10**res_exponent)

        w, h = surface.preview_options.render_size
        aspect_ratio = w / h

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

        # gaze on cache for timeline
        gaze_ons = np.concatenate([[0], gaze_ons])
        gaze_diff = np.diff(gaze_ons)
        start_times = self.recording.scene.time[gaze_diff == 1].tolist()
        stop_times = self.recording.scene.time[gaze_diff == -1].tolist()
        if len(stop_times) < len(start_times):
            stop_times.append(self.recording.scene[-1].time)

        gaze_upon_cache_data = list(zip(start_times, stop_times, strict=False))
        gaze_upon_file = self.get_cache_path() / f"{surface.uid}_gazes.pkl"
        with open(gaze_upon_file, "wb") as f:
            pickle.dump(gaze_upon_cache_data, f)

    def _load_surface_heatmap(self, surface_uid: str) -> None:
        surface = self.get_surface(surface_uid)
        cache_file = self.get_cache_path() / f"{surface_uid}_heatmap.png"
        surface._heatmap = cv2.imread(str(cache_file))
        self.trigger_scene_update()
        self.add_surface_gaze_timeline(surface)

    def recalculate_heatmap(self, surface_uid: str) -> None:
        cache_file = self.get_cache_path() / f"{surface_uid}_heatmap.png"
        if cache_file.exists():
            cache_file.unlink()

        self.get_surface(surface_uid)._heatmap = None
        self.trigger_scene_update()

        self.attempt_load_surface_heatmap(surface_uid)

    @property
    def draw_marker_ids(self) -> bool:
        return self._draw_marker_ids

    @draw_marker_ids.setter
    def draw_marker_ids(self, value: bool) -> None:
        self._draw_marker_ids = value

    @property
    def draw_names(self) -> bool:
        return self._draw_names

    @draw_names.setter
    def draw_names(self, value: bool) -> None:
        self._draw_names = value

    @property
    def export_overlays(self) -> bool:
        return self._export_overlays

    @export_overlays.setter
    def export_overlays(self, value: bool) -> None:
        self._export_overlays = value

    @property
    @property_params(
        prevent_add=True,
        item_params={"label_field": "name"},
        primary=True,
    )
    def surfaces(self) -> list["TrackedSurface"]:
        return self._surfaces

    @surfaces.setter
    def surfaces(self, value: list["TrackedSurface"]):  # noqa: C901
        frame_idx = self.get_scene_idx_for_time()
        new_surfaces = [surface for surface in value if surface not in self._surfaces]
        removed_surfaces = [
            surface for surface in self._surfaces if surface not in value
        ]

        fresh_surfaces = [s for s in new_surfaces if s.uid == ""]
        if len(fresh_surfaces) > 0:
            frame_detect_done = frame_idx < len(self.markers_by_frame)
            if not frame_detect_done or len(self.markers_by_frame[frame_idx]) < 1:
                QMessageBox.warning(
                    self.app.main_window,
                    "No markers detected",
                    "Markers must be detected on the current frame to add a surface.",
                )
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
                lambda s=surface: self.on_locations_invalidated(s)
            )

            locations_path = self.get_cache_path() / f"{surface.uid}_locations.npy"
            if locations_path.exists():
                self._load_surface_locations_cache(surface.uid)

            elif not self.app.headless:
                surface.defining_frame_index = int(frame_idx)
                self._start_bg_surface_locator(surface)

        for surface in removed_surfaces:
            if surface.edit:
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

            self.get_timeline().remove_timeline_plot(f"Surface: {surface.name}")
            self.get_timeline().remove_timeline_plot(f"Surface Gaze: {surface.name}")

        self.changed.emit()

    def on_marker_edit_changed(self, surface: "TrackedSurface") -> None:
        if surface.edit:
            for other_surface in self.surfaces:
                if other_surface != surface:
                    other_surface.edit = False

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
        job = self.job_manager.run_background_action(
            f"Detect Surface Locations [{surface.name}]",
            "SurfaceTrackingPlugin.bg_detect_surface_locations",
            surface.uid,
            *args,
            **kwargs,
        )
        surface.add_bg_job(job)
        job.finished.connect(lambda: self._load_surface_locations_cache(surface.uid))

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
            # @TODO: apply brightness/contrast adjustments
            markers_by_frame.append(detector.detect(frame.gray))

            yield ProgressUpdate((frame_idx + 1) / len(self.recording.scene))

        self.marker_cache_file.parent.mkdir(parents=True, exist_ok=True)
        with self.marker_cache_file.open("wb") as f:
            np.save(f, np.array(markers_by_frame, dtype=object))

    def bg_detect_surface_locations(
        self,
        uid: str,
    ) -> T.Generator[ProgressUpdate, None, None]:
        starting_frame_idx = self.get_surface(uid).defining_frame_index

        if starting_frame_idx >= len(self.markers_by_frame):
            logging.error("Marker detection not yet complete")
            return

        markers = self.markers_by_frame[starting_frame_idx]

        # load surface from disk
        surf_path = self.get_cache_path() / f"{uid}_surface.pkl"
        if surf_path.exists():
            with surf_path.open("rb") as f:
                tracker_surf = pickle.load(f)  # noqa: S301

        else:
            markers = self.markers_by_frame[starting_frame_idx]
            tracker_surf = Surface.from_apriltag_detections(uid, markers, self.camera)

        locations = []
        for frame_idx, markers in enumerate(self.markers_by_frame):
            location = tracker_surf.localize(markers, self.camera)
            locations.append(location)

            yield ProgressUpdate((frame_idx + 1) / len(self.markers_by_frame))

        locations_path = self.get_cache_path() / f"{uid}_locations.npy"
        locations_path.parent.mkdir(parents=True, exist_ok=True)
        with locations_path.open("wb") as f:
            np.save(f, np.array(locations, dtype=object))

        surf_path = self.get_cache_path() / f"{uid}_surface.pkl"
        with surf_path.open("wb") as f:
            pickle.dump(tracker_surf, f)

        visibility = np.array([1 if val else 0 for val in locations])
        visibility = np.concatenate([[0], visibility])
        viz_diff = np.diff(visibility)
        start_times = self.recording.scene.time[viz_diff == 1].tolist()
        stop_times = self.recording.scene.time[viz_diff == -1].tolist()
        if len(stop_times) < len(start_times):
            stop_times.append(self.recording.scene[-1].time)

        visibilities = list(zip(start_times, stop_times, strict=False))
        surf_viz_path = self.get_cache_path() / f"{uid}_surface_visibility.pkl"
        with surf_viz_path.open("wb") as f:
            pickle.dump(visibilities, f)

    def bg_export_surface_video(
        self, destination: Path, uid: str
    ) -> T.Generator[ProgressUpdate, None, None]:
        surface = self.get_surface(uid)

        start_time, stop_time = neon_player.instance().recording_settings.export_window
        start_mask = self.recording.scene.time >= start_time
        stop_mask = self.recording.scene.time <= stop_time
        scene_frames = self.recording.scene[start_mask & stop_mask]

        with plv.Writer(destination / f"{surface.name}_surface_view.mp4") as writer:
            for output_idx, scene_frame in enumerate(scene_frames):
                if scene_frame.index < len(self.surface_locations[uid]):
                    rel_ts = (scene_frame.time - start_time) / 1e9
                    frame = QImage(
                        *surface.preview_options.render_size,
                        QImage.Format.Format_BGR888,
                    )
                    painter = QPainter(frame)
                    surface.location = self.surface_locations[uid][scene_frame.index]
                    if not surface.location:
                        painter.fillRect(
                            0, 0, frame.width(), frame.height(), QColorConstants.Gray
                        )
                    else:
                        surface.render(painter, scene_frame.time)

                    painter.end()

                    frame_pixels = ndarray_from_qimage(frame)
                    av_frame = av.VideoFrame.from_ndarray(frame_pixels, format="bgr24")

                    plv_frame = plv.VideoFrame(av_frame, rel_ts, output_idx, "")
                    writer.write_frame(plv_frame)

                yield ProgressUpdate((output_idx + 1) / len(scene_frames))

    @action
    @action_params(compact=True, icon=QIcon(str(neon_player.asset_path("export.svg"))))
    def export(self, destination: Path = Path()) -> None:
        start_time, stop_time = neon_player.instance().recording_settings.export_window
        start_mask = self.recording.gaze.time >= start_time
        stop_mask = self.recording.gaze.time <= stop_time

        gazes_in_window = self.recording.gaze[start_mask & stop_mask]

        for surface in self._surfaces:
            surface.export_gazes(gazes_in_window, destination)
            try:
                surface.export_fixations(gazes_in_window, destination)
            except Exception:
                logging.warning(
                    "Failed to export surface fixations. Is fixation plugin enabled?"
                )


def insert_interpolated_points(points: npt.NDArray, n_between: int = 10) -> npt.NDArray:
    points = np.asarray(points, dtype=float)
    points = np.concatenate((points, points[0:1]), axis=0)

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
        out[idx : idx + n_between + 1] = segment[:-1]
        idx += n_between + 1

    # Append the final original point
    out[-1] = points[-1]

    return out
