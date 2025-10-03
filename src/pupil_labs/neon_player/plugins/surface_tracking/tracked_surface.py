import typing as T
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from PySide6.QtCore import QObject, QPointF, QSize, Signal
from PySide6.QtGui import QColor
from qt_property_widgets.utilities import PersistentPropertiesMixin, property_params
from surface_tracker import (
    CornerId,
    SurfaceLocation,
    SurfaceTracker,
)

from pupil_labs import neon_player
from pupil_labs.neon_player import Plugin, action
from pupil_labs.neon_player.plugins.gaze import CrosshairViz, GazeVisualization

from .ui import SurfaceHandle, SurfaceViewWidget


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
    def tracker_plugin(self) -> "SurfaceTrackingPlugin":
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

    def export_gazes(self, gazes, destination: Path):
        gaze_plugin = Plugin.get_instance_by_name("GazeDataPlugin")

        offset_gazes = gazes.point + np.array([
            gaze_plugin.offset_x * gaze_plugin.recording.scene.width,
            gaze_plugin.offset_y * gaze_plugin.recording.scene.height
        ])
        mapped_gazes = self.image_points_to_surface(offset_gazes)

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
