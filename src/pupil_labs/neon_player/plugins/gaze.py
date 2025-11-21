import enum
import logging
import typing as T
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pandas as pd
from pupil_labs.neon_recording import NeonRecording
from PySide6.QtCore import QObject, QPointF, Signal
from PySide6.QtGui import QColor, QPainter
from qt_property_widgets.utilities import PersistentPropertiesMixin, property_params

from pupil_labs import neon_player
from pupil_labs.neon_player import action
from pupil_labs.neon_player.utilities import (
    cart_to_spherical,
    find_ranged_index,
    get_scene_intrinsics,
    unproject_points,
)


class Aggregation(enum.Enum):
    Raw = "Raw"
    Mean = "Mean"
    Median = "Median"
    First = "First"
    Last = "Last"

    def apply(self, samples):
        if self is Aggregation.Raw or len(samples) == 0:
            v = samples

        elif self is Aggregation.Mean:
            v = samples.mean(axis=0)

        elif self is Aggregation.Median:
            v = np.median(samples, axis=0)

        elif self is Aggregation.First:
            v = samples[0]

        elif self is Aggregation.Last:
            v = samples[-1]

        if len(samples.shape) > 1:
            return v.reshape(-1, samples.shape[-1])

        else:
            return v


class GazeDataPlugin(neon_player.Plugin):
    label = "Gaze Data"
    offset_changed = Signal()

    def __init__(self) -> None:
        super().__init__()

        self.render_layer = 10
        self._offset_x = 0.0
        self._offset_y = 0.0

        self._visualizations: list[GazeVisualization] = [
            CircleViz(),
        ]

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        for viz in self._visualizations:
            viz.on_recording_loaded(recording)

        try:
            worn_data = self.recording.worn[["time", "worn"]]
            if len(worn_data) == 0:
                return
        except Exception:
            logging.exception("Failed to load worn data")
            return

        worn_on = self.recording.worn["worn"] // 255
        worn_on = np.concatenate([[0], worn_on])
        state_diff = np.diff(worn_on.astype(int))

        start_times = worn_data[state_diff == 1][:, 0].tolist()
        stop_times = worn_data[state_diff == -1][:, 0].tolist()

        if len(stop_times) < len(start_times):
            stop_times.append(worn_data[-1][0])

        self.get_timeline().add_timeline_broken_bar(
            "Worn",
            list(zip(start_times, stop_times, strict=False)),
        )

    def render(self, painter: QPainter, time_in_recording: int) -> None:
        if self.recording is None:
            return

        scene_idx = self.get_scene_idx_for_time(time_in_recording)
        if scene_idx >= len(self.recording.scene) or scene_idx < 0:
            return

        samples = self.get_gazes_for_scene(scene_idx)
        gazes = samples.point
        offset_gazes = gazes + np.array([
            self._offset_x * self.recording.scene.width,
            self._offset_y * self.recording.scene.height,
        ])

        worns = self.recording.worn.sample(samples.time).worn

        aggregations = {}
        offset_aggregations = {}
        worn_aggregations = {}
        for viz in self._visualizations:
            if viz._aggregation not in aggregations:
                aggregations[viz._aggregation] = viz._aggregation.apply(gazes)
                offset_aggregations[viz._aggregation] = viz._aggregation.apply(offset_gazes)
                worn_aggregations[viz._aggregation] = viz._aggregation.apply(worns)

            aggregation_dict = offset_aggregations if viz.use_offset else aggregations

            renderable_mask = np.array([False] * len(aggregation_dict[viz._aggregation]))
            if viz.show_when_worn:
                mask = worn_aggregations[viz._aggregation] >= 128
                renderable_mask = renderable_mask | mask

            if viz.show_when_not_worn:
                mask = worn_aggregations[viz._aggregation] < 128
                renderable_mask = renderable_mask | mask

            viz.render(
                painter,
                aggregation_dict[viz._aggregation][renderable_mask],
            )

    def get_gazes_for_scene(self, scene_idx: int = -1):
        if scene_idx < 0:
            scene_idx = self.get_scene_idx_for_time()

        gaze_start_time = self.recording.scene[scene_idx].time
        after_mask = self.recording.gaze.time >= gaze_start_time

        if scene_idx < len(self.recording.scene) - 1:
            gaze_end_ts = self.recording.scene[scene_idx + 1].time
            before_mask = self.recording.gaze.time < gaze_end_ts
            time_mask = after_mask & before_mask
        else:
            time_mask = after_mask

        return self.recording.gaze[time_mask]

    @action
    def export(self, destination: Path = Path()) -> None:
        if self.recording is None:
            return

        start_time, stop_time = neon_player.instance().recording_settings.export_window
        start_mask = self.recording.gaze.time >= start_time
        stop_mask = self.recording.gaze.time <= stop_time

        export_gazes = self.recording.gaze[start_mask & stop_mask]
        export_worn = self.recording.worn[start_mask & stop_mask]

        scene_camera_matrix, scene_distortion_coefficients = get_scene_intrinsics(
            self.recording
        )

        matched_fixation_ids = (
            find_ranged_index(
                export_gazes.time,
                self.recording.fixations.start_time,
                self.recording.fixations.stop_time
            ) + 1
        )

        matched_blink_ids = (
            find_ranged_index(
                export_gazes.time,
                self.recording.blinks.start_time,
                self.recording.blinks.stop_time
            ) + 1
        )

        spherical_coords = cart_to_spherical(
            unproject_points(
                export_gazes.point,
                scene_camera_matrix,
                scene_distortion_coefficients,
            )
        )

        gaze = pd.DataFrame({
            "recording id": self.recording.info["recording_id"],
            "timestamp [ns]": export_gazes.time,
            "gaze x [px]": export_gazes.point[:, 0],
            "gaze y [px]": export_gazes.point[:, 1],
            "worn": export_worn.worn,
            "fixation id": matched_fixation_ids,
            "blink id": matched_blink_ids,
            "azimuth [deg]": spherical_coords[2],
            "elevation [deg]": spherical_coords[1],
        })

        gaze["fixation id"] = gaze["fixation id"].replace(0, None)
        gaze["blink id"] = gaze["blink id"].replace(0, None)

        export_file = destination / "gaze.csv"
        gaze.to_csv(export_file, index=False)

        logging.info(f"Wrote {export_file}")

    @property
    @property_params(min=-1, max=1, step=0.01, decimals=3)
    def offset_x(self) -> float:
        return self._offset_x

    @offset_x.setter
    def offset_x(self, value: float) -> None:
        self._offset_x = value
        self.offset_changed.emit()

    @property
    @property_params(min=-1, max=1, step=0.01, decimals=3)
    def offset_y(self) -> float:
        return self._offset_y

    @offset_y.setter
    def offset_y(self, value: float) -> None:
        self._offset_y = value
        self.offset_changed.emit()

    @property
    @property_params(
        use_subclass_selector=True,
        add_button_text="Add visualization",
        item_params={"label_field": "label"},
    )
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
        self._aggregation = Aggregation.Mean
        self._show_when_worn = True
        self._show_when_not_worn = False

        self.recording: NeonRecording | None = None

    def render(
        self,
        painter: QPainter,
        gazes: npt.NDArray[np.float64],
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

    @property
    def aggregation(self) -> Aggregation:
        return self._aggregation

    @aggregation.setter
    def aggregation(self, value: Aggregation) -> None:
        self._aggregation = value

    @property
    def show_when_worn(self) -> bool:
        return self._show_when_worn

    @show_when_worn.setter
    def show_when_worn(self, value: bool) -> None:
        self._show_when_worn = value

    @property
    def show_when_not_worn(self) -> bool:
        return self._show_when_not_worn

    @show_when_not_worn.setter
    def show_when_not_worn(self, value: bool) -> None:
        self._show_when_not_worn = value


class CircleViz(GazeVisualization):
    label = "Circle"

    def __init__(self) -> None:
        super().__init__()
        self._color = QColor(255, 0, 0, 128)
        self._radius = 30
        self._stroke_width = 10

    def render(
        self,
        painter: QPainter,
        gazes: npt.NDArray[np.float64]
    ) -> None:
        pen = painter.pen()
        pen.setWidth(self._stroke_width)
        pen.setColor(self._color)
        painter.setPen(pen)

        for gaze in gazes:
            center = QPointF(gaze[0], gaze[1])
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
    label = "Crosshair"

    def __init__(self) -> None:
        super().__init__()
        self._color = QColor(0, 255, 0, 128)
        self._size = 40
        self._gap_size = 20
        self._stroke_width = 5
        self._draw_dot = True

    def render(
        self,
        painter: QPainter,
        gazes: npt.NDArray[np.float64],
    ) -> None:
        brush = painter.brush()
        pen = painter.pen()
        pen.setColor("#00000000")
        painter.setPen(pen)
        painter.setBrush(self._color)

        if self._draw_dot:
            for gaze in gazes:
                center = QPointF(gaze[0], gaze[1])

                painter.drawEllipse(center, self._stroke_width / 2, self._stroke_width / 2)

        pen.setWidth(self._stroke_width)
        pen.setColor(self._color)
        painter.setPen(pen)

        for gaze in gazes:
            center = QPointF(gaze[0], gaze[1])

            # Draw horizontal lines
            painter.drawLine(
                QPointF(center.x() - self._gap_size, center.y()),
                QPointF(center.x() - self._gap_size - self._size, center.y()),
            )
            painter.drawLine(
                QPointF(center.x() + self._gap_size + self._size, center.y()),
                QPointF(center.x() + self._gap_size, center.y()),
            )

            # Draw vertical lines
            painter.drawLine(
                QPointF(center.x(), center.y() - self._gap_size),
                QPointF(center.x(), center.y() - self._gap_size - self._size),
            )

            painter.drawLine(
                QPointF(center.x(), center.y() + self._gap_size),
                QPointF(center.x(), center.y() + self._gap_size + self._size),
            )

        painter.setBrush(brush)

    @property
    def color(self) -> QColor:
        return self._color

    @color.setter
    def color(self, value: QColor) -> None:
        self._color = value

    @property
    @property_params(min=0, max=1920)
    def size(self) -> int:
        return self._size

    @size.setter
    def size(self, value: int) -> None:
        self._size = value

    @property
    @property_params(min=0, max=1920)
    def gap_size(self) -> int:
        return self._gap_size

    @gap_size.setter
    def gap_size(self, value: int) -> None:
        self._gap_size = value

    @property
    @property_params(min=1, max=100)
    def stroke_width(self) -> int:
        return self._stroke_width

    @stroke_width.setter
    def stroke_width(self, value: int) -> None:
        self._stroke_width = value

    @property
    def draw_dot(self) -> bool:
        return self._draw_dot

    @draw_dot.setter
    def draw_dot(self, value: bool) -> None:
        self._draw_dot = value
