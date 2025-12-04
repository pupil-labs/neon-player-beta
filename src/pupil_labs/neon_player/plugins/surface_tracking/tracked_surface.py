import logging
import typing as T
from enum import Enum
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from PySide6.QtCore import QObject, QPointF, QSize, Signal
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QFileDialog
from qt_property_widgets.utilities import (
    PersistentPropertiesMixin,
    action_params,
    property_params,
)
from surface_tracker import (
    CornerId,
    SurfaceLocation,
    SurfaceTracker,
)

from pupil_labs import neon_player
from pupil_labs.neon_player import Plugin, action
from pupil_labs.neon_player.plugins.gaze import CrosshairViz, GazeVisualization
from pupil_labs.neon_player.utilities import qimage_from_frame

from .ui import SurfaceHandle, SurfaceViewWindow


class ColorMap(Enum):
    Autumn = cv2.COLORMAP_AUTUMN
    Bone = cv2.COLORMAP_BONE
    Jet = cv2.COLORMAP_JET
    Winter = cv2.COLORMAP_WINTER
    Rainbow = cv2.COLORMAP_RAINBOW
    Ocean = cv2.COLORMAP_OCEAN
    Summer = cv2.COLORMAP_SUMMER
    Spring = cv2.COLORMAP_SPRING
    Cool = cv2.COLORMAP_COOL
    Hsv = cv2.COLORMAP_HSV
    Pink = cv2.COLORMAP_PINK
    Hot = cv2.COLORMAP_HOT
    Parula = cv2.COLORMAP_PARULA
    Magma = cv2.COLORMAP_MAGMA
    Inferno = cv2.COLORMAP_INFERNO
    Plasma = cv2.COLORMAP_PLASMA
    Viridis = cv2.COLORMAP_VIRIDIS
    Cividis = cv2.COLORMAP_CIVIDIS
    Twilight = cv2.COLORMAP_TWILIGHT
    Twilight_Shifted = cv2.COLORMAP_TWILIGHT_SHIFTED
    Turbo = cv2.COLORMAP_TURBO
    Deepgreen = cv2.COLORMAP_DEEPGREEN


class SurfaceViewDisplayOptions(PersistentPropertiesMixin, QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._tracked_surface = None
        self._render_size = QSize(400, 400)
        self._visualizations: list[GazeVisualization] = [
            CrosshairViz(),
        ]

    @property
    @property_params(min=1, max=2560)
    def width(self) -> int:
        return self._render_size.width()

    @width.setter
    def width(self, value: int) -> None:
        self._render_size.setWidth(value)

    @property
    @property_params(min=1, max=2560)
    def height(self) -> int:
        return self._render_size.height()

    @height.setter
    def height(self, value: int) -> None:
        self._render_size.setHeight(value)

    @property
    @property_params(
        use_subclass_selector=True,
        add_button_text="Add visualization",
        item_params={ "label_field": "label" }
    )
    def visualizations(self) -> list["GazeVisualization"]:
        return self._visualizations

    @visualizations.setter
    def visualizations(self, value: list["GazeVisualization"]) -> None:
        self._visualizations = value

        for viz in self._visualizations:
            viz.changed.connect(self.changed.emit)

    @action
    @action_params(
        compact=True,
        icon=QIcon.fromTheme("document-save")
    )
    def export_video(self, destination: Path = Path()):
        tracker_plugin = Plugin.get_instance_by_name("SurfaceTrackingPlugin")
        self.export_job = tracker_plugin.job_manager.run_background_action(
            f"{self._tracked_surface.name} Surface Video Export",
            "SurfaceTrackingPlugin.bg_export_surface_video",
            destination,
            self._tracked_surface.uid
        )

        return self.export_job

    @action
    @action_params(
        compact=True,
        icon=QIcon.fromTheme("document-save")
    )
    def export_current_frame(self):
        file_path_str, _ = QFileDialog.getSaveFileName(
            None, "Export surface frame", "", "PNG Images (*.png)"
        )
        if not file_path_str:
            return

        if not file_path_str.endswith(".png"):
            file_path_str += ".png"

        image = self._frame_image()
        image.save(file_path_str)

    @action
    def copy_frame_to_clipboard(self) -> None:
        clipboard = neon_player.instance().clipboard()
        clipboard.setPixmap(QPixmap.fromImage(self._frame_image()))

    def _frame_image(self) -> QImage:
        frame = QImage(self._render_size, QImage.Format.Format_RGB32)
        painter = QPainter(frame)
        self._tracked_surface.render(painter)
        painter.end()

        return frame


class TrackedSurface(PersistentPropertiesMixin, QObject):
    changed = Signal()
    locations_invalidated = Signal()
    surface_location_changed = Signal()
    view_requested = Signal(object)
    marker_edit_changed = Signal()
    heatmap_invalidated = Signal()

    label = "Surface"

    def __init__(self) -> None:
        super().__init__()
        self._uid = ""
        self._name = ""
        self._markers = []
        self._can_edit = False
        self._preview_options = SurfaceViewDisplayOptions()
        self._preview_options._tracked_surface = self
        self._show_heatmap = False
        self._heatmap_smoothness = 0.35
        self._heatmap_alpha = .75
        self._heatmap = None
        self._heatmap_color = ColorMap.Jet

        self.tracker_surface = None

        self._location = None

        self.preview_window = None
        self.handle_widgets = {}
        self.corner_positions = {}
        self.jobs = []

        neon_player.instance().recording_settings.export_window_changed.connect(
            self.heatmap_invalidated.emit
        )
        Plugin.get_instance_by_name("GazeDataPlugin").offset_changed.connect(
            self.heatmap_invalidated.emit
        )

    def add_bg_job(self, job):
        for j in self.jobs:
            j.cancel()

        self.jobs.append(job)
        job.finished.connect(lambda: self.jobs.remove(job))
        job.canceled.connect(lambda: self.jobs.remove(job))

    def __del__(self):
        self.cleanup_widgets()

    def to_dict(self) -> dict[str, T.Any]:
        state = super().to_dict()
        state["edit"] = False
        return state

    @classmethod
    def from_dict(
        cls: type["TrackedSurface"], state: dict[str, T.Any]
    ) -> T.Any:
        item = super().from_dict(state)
        item._preview_options._tracked_surface = item
        return item

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
            t1 = value.transform_matrix_from_image_to_surface_undistorted
            t2 = self._location.transform_matrix_from_image_to_surface_undistorted
            if np.all(t1 == t2):
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
            w.set_scene_pos(distorted_corner)

    def recalculate_heatmap(self):
        Plugin.get_instance_by_name("SurfaceTrackingPlugin").recalculate_heatmap(self.uid)

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, name: str) -> None:
        self._name = name

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
    def edit(self) -> bool:
        return self._can_edit

    @edit.setter
    def edit(self, value: bool) -> None:
        self._can_edit = value
        self.marker_edit_changed.emit()

        if not value:
            self.cleanup_widgets()

        else:
            app = neon_player.instance()
            vrw = app.main_window.video_widget

            self.handle_widgets = {
                corner: SurfaceHandle(self, corner)
                for corner in CornerId.all_corners()
            }

            for corner_id, w in self.handle_widgets.items():
                w.setFixedSize(20, 20)
                w.setParent(vrw)
                w.position_changed.connect(
                    lambda pos, corner=corner_id: self.on_corner_changed(corner, pos)
                )

            self.update_handle_positions()

    @property
    def show_heatmap(self) -> bool:
        return self._show_heatmap

    @show_heatmap.setter
    def show_heatmap(self, value: bool) -> None:
        self._show_heatmap = value

    @property
    @property_params(min=0, max=1)
    def heatmap_smoothness(self) -> float:
        return self._heatmap_smoothness

    @heatmap_smoothness.setter
    def heatmap_smoothness(self, value: float) -> None:
        self._heatmap_smoothness = value
        self.heatmap_invalidated.emit()

    @property
    @property_params(min=0, max=1)
    def heatmap_alpha(self) -> float:
        return self._heatmap_alpha

    @heatmap_alpha.setter
    def heatmap_alpha(self, value: float) -> None:
        self._heatmap_alpha = value

    @property
    def heatmap_color(self) -> ColorMap:
        return self._heatmap_color

    @heatmap_color.setter
    def heatmap_color(self, value: ColorMap) -> None:
        self._heatmap_color = value

    @property
    @property_params(widget=None)
    def uid(self) -> str:
        return self._uid

    @uid.setter
    def uid(self, value: str):
        self._uid = value

    @property
    @property_params(widget=None, dont_encode=True)
    def tracker_plugin(self) -> "SurfaceTrackingPlugin":
        return Plugin.get_instance_by_name("SurfaceTrackingPlugin")

    @property
    @property_params(widget=None, dont_encode=True)
    def tracker(self) -> SurfaceTracker:
        return self.tracker_plugin.tracker

    @property
    @property_params(widget=None)
    def preview_options(self) -> SurfaceViewDisplayOptions:
        return self._preview_options

    @preview_options.setter
    def preview_options(self, value: SurfaceViewDisplayOptions) -> None:
        self._preview_options = value

    def image_points_to_surface(self, points):
        undistorted_points = self.tracker_plugin.camera.undistort_points(points)
        return cv2.perspectiveTransform(
            undistorted_points.reshape(-1, 1, 2),
            self.location.transform_matrix_from_image_to_surface_undistorted
        ).reshape(-1, 2)

    def apply_offset_and_map_gazes(self, gazes):
        try:
            gaze_plugin = Plugin.get_instance_by_name("GazeDataPlugin")
        except KeyError:
            logging.warning(
                "Surface fixations export requires gaze and fixations plugins to be enabled."
            )
            return

        offset_gazes = gazes.point + np.array([
            gaze_plugin.offset_x * gaze_plugin.recording.scene.width,
            gaze_plugin.offset_y * gaze_plugin.recording.scene.height
        ])
        return self.image_points_to_surface(offset_gazes)

    def export_gazes(self, gazes, destination: Path = Path()):
        mapped_gazes = self.apply_offset_and_map_gazes(gazes)

        lower_pass = np.all(mapped_gazes >= 0, axis=1)
        upper_pass = np.all(mapped_gazes <= 1.0, axis=1)
        gazes_on_surface = lower_pass & upper_pass

        gazes = pd.DataFrame({
            "timestamp [ns]": gazes.time,
            "gaze detected on surface": gazes_on_surface,
            "gaze position on surface x [normalized]": mapped_gazes[:, 0],
            "gaze position on surface y [normalized]": mapped_gazes[:, 1],
        })

        gazes.to_csv(
            destination / f"gaze_positions_on_surface_{self.name}.csv",
            index=False
        )

        cv2.imwrite(
            destination / f"{self.name}_heatmap.png",
            cv2.applyColorMap(self._heatmap, self.heatmap_color.value)
        )

    def export_fixations(self, gazes, destination: Path = Path()):
        try:
            gaze_plugin = Plugin.get_instance_by_name("GazeDataPlugin")
            fixations_plugin = Plugin.get_instance_by_name("FixationsPlugin")
        except KeyError:
            logging.warning(
                "Surface fixations export requires gaze and fixations plugins to be enabled."
            )
            return

        fixation_data = fixations_plugin.get_export_data()
        fixation_data["fixation detected on surface"] = 0

        fixation_points = fixation_data[["fixation x [px]", "fixation y [px]"]]
        mapped_fixation_points = self.image_points_to_surface(fixation_points)

        fixation_data["fixation x [normalized]"] = mapped_fixation_points[:, 0]
        fixation_data["fixation y [normalized]"] = mapped_fixation_points[:, 1]

        gaze_offset = np.array([
            gaze_plugin.offset_x * gaze_plugin.recording.scene.width,
            gaze_plugin.offset_y * gaze_plugin.recording.scene.height
        ])

        fixations_on_surfs = []
        for fixation in fixation_data.iterrows():
            start_mask = gazes.time >= fixation[1]["start timestamp [ns]"]
            end_mask = gazes.time <= fixation[1]["end timestamp [ns]"]
            fixation_gazes = gazes[start_mask & end_mask]
            offset_gazes = fixation_gazes.point + gaze_offset
            mapped_gazes = self.image_points_to_surface(offset_gazes)

            lower_pass = np.all(mapped_gazes >= 0, axis=1)
            upper_pass = np.all(mapped_gazes <= 1.0, axis=1)
            gazes_on_surface = lower_pass & upper_pass

            fixations_on_surfs.append(np.mean(gazes_on_surface))

        fixation_data["fixation detected on surface"] = fixations_on_surfs

        # drop unused columns
        fixation_data = fixation_data.drop(columns=[
            "recording id",
            "fixation x [px]",
            "fixation y [px]",
            "azimuth [deg]",
            "elevation [deg]",
        ])

        fixation_data.to_csv(
            destination / f"fixations_on_surface_{self.name}.csv",
            index=False
        )

    def render(self, painter: QPainter, time_in_recording: int = -1) -> None:
        if self.location is None:
            return

        if time_in_recording == -1:
            time_in_recording = neon_player.instance().current_ts

        camera = self.tracker_plugin.camera
        gaze_plugin = Plugin.get_instance_by_name("GazeDataPlugin")

        app = neon_player.instance()
        scene_idx = gaze_plugin.get_scene_idx_for_time(time_in_recording)
        scene_frame = app.recording.scene[scene_idx]
        undistorted_image = camera.undistort_image(scene_frame.bgr)

        dst_size = (self.preview_options.width, self.preview_options.height)
        S = np.float64([
            [dst_size[0], 0.0,   0.0],
            [0.0,   dst_size[1], 0.0],
            [0.0,   0.0,   1.0]
        ])
        h_scaled = S @ self.location.transform_matrix_from_image_to_surface_undistorted

        surface_image = cv2.warpPerspective(undistorted_image, h_scaled, dst_size)

        painter.drawImage(0, 0, qimage_from_frame(surface_image))

        gazes = gaze_plugin.get_gazes_for_scene(scene_idx).point

        mapped_gazes = self.image_points_to_surface(gazes)
        mapped_gazes[:, 0] *= self.preview_options.width
        mapped_gazes[:, 1] *= self.preview_options.height
        offset_gazes = None

        aggregations = {}
        offset_aggregations = {}
        for viz in self.preview_options.visualizations:
            if viz.use_offset:
                if offset_gazes is None:
                    offset_gazes = gazes + np.array([
                        gaze_plugin.offset_x * scene_frame.width,
                        gaze_plugin.offset_y * scene_frame.height
                    ])
                    mapped_offset_gazes = self.image_points_to_surface(offset_gazes)
                    mapped_offset_gazes[:, 0] *= self.preview_options.width
                    mapped_offset_gazes[:, 1] *= self.preview_options.height

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

    @action
    @action_params(
        compact=True,
        icon=QIcon.fromTheme("window-new"),
    )
    def view_surface(self) -> None:
        self.preview_window = SurfaceViewWindow(self)
        self.preview_window.show()

        width = min(1024, max(self.preview_options.width, 400))
        aspect = self.preview_options.width / self.preview_options.height
        self.preview_window.resize(width + 300, width / aspect)

    @action
    @action_params(
        compact=True,
        icon=QIcon.fromTheme("object-rotate-right"),
    )
    def rotate(self) -> None:
        markers = self.tracker_surface._registered_markers_by_uid_undistorted.values()
        for marker in markers:
            for pos in marker._Marker__vertices_by_corner_id.values():
                x, y = pos
                pos[:] = np.array([y, 1.0 - x], dtype=np.float32)

        self.locations_invalidated.emit()
