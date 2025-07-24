import logging
import typing as T
from pathlib import Path

import numpy as np
import pandas as pd
from PySide6.QtCore import QObject, QPointF, Signal
from PySide6.QtGui import QColor, QPainter
from qt_property_widgets.utilities import PersistentPropertiesMixin, property_params

import pupil_labs.neon_recording as nr
from pupil_labs import neon_player
from pupil_labs.neon_player import action
from pupil_labs.neon_player.utilities import (
    cart_to_spherical,
    find_ranged_index,
    get_scene_intrinsics,
    unproject_points,
)
from pupil_labs.neon_recording import NeonRecording
from pupil_labs.neon_recording.timeseries.gaze import GazeArray


def bg_export(recording_path: Path, destination: Path) -> None:
    recording = nr.open(recording_path)

    scene_camera_matrix, scene_distortion_coefficients = get_scene_intrinsics(recording)
    fixations = recording.fixations[recording.fixations["event_type"] == 1]

    fixation_ids = (
        find_ranged_index(recording.gaze.ts, fixations.start_ts, fixations.end_ts) + 1
    )

    blink_ids = (
        find_ranged_index(
            recording.gaze.ts, recording.blinks.start_ts, recording.blinks.end_ts
        )
        + 1
    )

    spherical_coords = cart_to_spherical(
        unproject_points(
            recording.gaze.xy,
            scene_camera_matrix,
            scene_distortion_coefficients,
        )
    )

    gaze = pd.DataFrame({
        "recording id": recording.info["recording_id"],
        "timestamp [ns]": recording.gaze.ts,
        "gaze x [px]": recording.gaze.x,
        "gaze y [px]": recording.gaze.y,
        "worn": recording.worn.worn,
        "fixation id": fixation_ids,
        "blink id": blink_ids,
        "azimuth [deg]": spherical_coords[2],
        "elevation [deg]": spherical_coords[1],
    })

    gaze["fixation id"] = gaze["fixation id"].replace(0, None)
    gaze["blink id"] = gaze["blink id"].replace(0, None)

    export_file = destination / "gaze.csv"
    gaze.to_csv(export_file, index=False)

    logging.info(f"Wrote {export_file}")


class GazeDataPlugin(neon_player.Plugin):
    label = "Gaze Data"

    def __init__(self) -> None:
        super().__init__()

        self._offset_x = 0.0
        self._offset_y = 0.0

        self._visualizations: list[GazeVisualization] = [
            AnnulusViz(),
        ]

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        for viz in self._visualizations:
            viz.on_recording_loaded(recording)

    def render(self, painter: QPainter, time_in_recording: int) -> None:
        if self.recording is None:
            return

        scene_idx = np.searchsorted(self.recording.scene.time, time_in_recording) - 1
        if scene_idx >= len(self.recording.scene) - 1 or scene_idx < 0:
            gaze_start_ts = time_in_recording
            gaze_end_ts = gaze_start_ts + 1e9 / 30

        else:
            gaze_start_ts = self.recording.scene[scene_idx].time
            gaze_end_ts = self.recording.scene[scene_idx + 1].time

        after_mask = self.recording.gaze.time >= gaze_start_ts
        before_mask = self.recording.gaze.time < gaze_end_ts
        gazes = self.recording.gaze[after_mask & before_mask]

        for viz in self._visualizations:
            viz.render(painter, gazes, self._offset_x, self._offset_y)

    @action
    def export(self, destination: Path = Path()) -> None:
        if self.recording is None:
            return

        self.app.job_manager.create_job(
            "Export Gaze Data", bg_export, self.recording._rec_dir, destination
        )

    @property
    @property_params(min=-1, max=1, step=0.01, decimals=3)
    def offset_x(self) -> float:
        return self._offset_x

    @offset_x.setter
    def offset_x(self, value: float) -> None:
        self._offset_x = value

    @property
    @property_params(min=-1, max=1, step=0.01, decimals=3)
    def offset_y(self) -> float:
        return self._offset_y

    @offset_y.setter
    def offset_y(self, value: float) -> None:
        self._offset_y = value

    @property
    @property_params(use_subclass_selector=True, add_button_text="Add visualization")
    def visualizations(self) -> list["GazeVisualization"]:
        return self._visualizations

    @visualizations.setter
    def visualizations(self, value: list["GazeVisualization"]) -> None:
        self._visualizations = value

        for viz in self._visualizations:
            viz.changed.connect(self.changed.emit)
            if self.recording is not None:
                viz.on_recording_loaded(self.recording)


class GazeVisualization(PersistentPropertiesMixin, QObject):
    changed = Signal()

    _known_types: T.ClassVar[list] = []

    def __init__(self) -> None:
        super().__init__()
        self._use_offset = True
        self.recording: NeonRecording | None = None

    def render(
        self,
        painter: QPainter,
        gazes: GazeArray,
        offset_x: float,
        offset_y: float,
    ) -> None:
        raise NotImplementedError("Subclasses must implement this method")

    def __init_subclass__(cls: type["GazeVisualization"], **kwargs: dict) -> None:
        GazeVisualization._known_types.append(cls)

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        self.recording = recording

    def to_dict(self, include_class_name: bool = True) -> dict:
        return super().to_dict(include_class_name=include_class_name)

    @property
    def use_offset(self) -> bool:
        return self._use_offset

    @use_offset.setter
    def use_offset(self, value: bool) -> None:
        self._use_offset = value


class AnnulusViz(GazeVisualization):
    def __init__(self) -> None:
        super().__init__()
        self._color = QColor(255, 0, 0, 128)
        self._radius = 30
        self._stroke_width = 10

    def render(
        self,
        painter: QPainter,
        gazes: GazeArray,
        offset_x: float,
        offset_y: float,
    ) -> None:
        if self.recording is None:
            return

        pen = painter.pen()
        pen.setWidth(self._stroke_width)
        pen.setColor(self._color)
        painter.setPen(pen)

        offset = [0.0, 0.0]

        if self._use_offset:
            if self.recording.scene.width:
                offset[0] = offset_x * self.recording.scene.width
            if self.recording.scene.height:
                offset[1] = offset_y * self.recording.scene.height

        for gaze in gazes:
            center = QPointF(gaze.point[0] + offset[0], gaze.point[1] + offset[1])
            painter.drawEllipse(center, self._radius, self._radius)

    @property
    def color(self) -> QColor:
        return self._color

    @color.setter
    def color(self, value: QColor) -> None:
        self._color = value

    @property
    @property_params(min=1, max=999)
    def radius(self) -> int:
        return self._radius

    @radius.setter
    def radius(self, value: int) -> None:
        self._radius = value

    @property
    @property_params(min=1, max=999)
    def stroke_width(self) -> int:
        return self._stroke_width

    @stroke_width.setter
    def stroke_width(self, value: int) -> None:
        self._stroke_width = value


class CrosshairViz(GazeVisualization):
    def __init__(self) -> None:
        super().__init__()
        self._color = QColor(0, 255, 0, 128)
        self._size = 20
        self._stroke_width = 5

    def render(
        self, painter: QPainter, gazes: GazeArray, offset_x: float, offset_y: float
    ) -> None:
        if self.recording is None:
            return

        pen = painter.pen()
        pen.setWidth(self._stroke_width)
        pen.setColor(self._color)
        painter.setPen(pen)

        offset = [0.0, 0.0]

        if self._use_offset:
            if self.recording.scene.width:
                offset[0] = offset_x * self.recording.scene.width
            if self.recording.scene.height:
                offset[1] = offset_y * self.recording.scene.height

        for gaze in gazes:
            center = QPointF(gaze.point[0] + offset[0], gaze.point[1] + offset[1])

            # Draw horizontal line
            painter.drawLine(
                QPointF(center.x() - self._size, center.y()),
                QPointF(center.x() + self._size, center.y()),
            )

            # Draw vertical line
            painter.drawLine(
                QPointF(center.x(), center.y() - self._size),
                QPointF(center.x(), center.y() + self._size),
            )

    @property
    def color(self) -> QColor:
        return self._color

    @color.setter
    def color(self, value: QColor) -> None:
        self._color = value

    @property
    @property_params(min=1, max=999)
    def size(self) -> int:
        return self._size

    @size.setter
    def size(self, value: int) -> None:
        self._size = value

    @property
    @property_params(min=1, max=999)
    def stroke_width(self) -> int:
        return self._stroke_width

    @stroke_width.setter
    def stroke_width(self, value: int) -> None:
        self._stroke_width = value
