import typing as T
from pathlib import Path
from typing import ClassVar, Optional

import cv2
import numpy as np
import pandas as pd
from PySide6.QtCore import QObject, QPointF, Signal
from PySide6.QtGui import QColor, QPainter
from qt_property_widgets.utilities import PersistentPropertiesMixin, property_params

import pupil_labs.neon_recording as nr
from pupil_labs import neon_player
from pupil_labs.neon_player import BGWorker, action
from pupil_labs.neon_recording import NeonRecording
from pupil_labs.neon_recording.stream.gaze_stream import GazeArray


def unproject_points(
    points_2d: T.Union[np.ndarray, list],
    camera_matrix: T.Union[np.ndarray, list],
    distortion_coefs: T.Union[np.ndarray, list],
    normalize: bool = False,
) -> np.ndarray:
    """Undistorts points according to the camera model.

    :param pts_2d, shape: Nx2
    :return: Array of unprojected 3d points, shape: Nx3
    """
    # Convert type to numpy arrays (OpenCV requirements)
    camera_matrix = np.array(camera_matrix)
    distortion_coefs = np.array(distortion_coefs)
    points_2d = np.asarray(points_2d, dtype=np.float32)

    # Add third dimension the way cv2 wants it
    points_2d = points_2d.reshape((-1, 1, 2))

    # Undistort 2d pixel coordinates
    points_2d_undist = cv2.undistortPoints(points_2d, camera_matrix, distortion_coefs)
    # Unproject 2d points into 3d directions; all points. have z=1
    points_3d = cv2.convertPointsToHomogeneous(points_2d_undist)
    points_3d.shape = -1, 3

    if normalize:
        # normalize vector length to 1
        points_3d /= np.linalg.norm(points_3d, axis=1)[:, np.newaxis]  # type: ignore

    return points_3d


def cart_to_spherical(
    points_3d: np.ndarray, apply_rad2deg: bool = True
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    points_3d = np.asarray(points_3d)
    # convert cartesian to spherical coordinates
    # source: http://stackoverflow.com/questions/4116658/faster-numpy-cartesian-to-spherical-coordinate-conversion
    x = points_3d[:, 0]
    y = points_3d[:, 1]
    z = points_3d[:, 2]
    radius = np.sqrt(x**2 + y**2 + z**2)
    # elevation: vertical direction
    #   positive numbers point up
    #   negative numbers point bottom
    elevation = np.arccos(y / radius) - np.pi / 2
    # azimuth: horizontal direction
    #   positive numbers point right
    #   negative numbers point left
    azimuth = np.pi / 2 - np.arctan2(z, x)

    if apply_rad2deg:
        elevation = np.rad2deg(elevation)
        azimuth = np.rad2deg(azimuth)

    return radius, elevation, azimuth


def find_ranged_index(
    values: np.ndarray, left_boundaries: np.ndarray, right_boundaries: np.ndarray
) -> np.ndarray:
    left_ids = np.searchsorted(left_boundaries, values, side="right") - 1
    right_ids = np.searchsorted(right_boundaries, values, side="right")

    return np.where(left_ids == right_ids, left_ids, -1)


def bg_export(recording_path: Path, destination: Path) -> None:
    recording = nr.open(recording_path)
    if not recording.calibration:
        scene_camera_matrix = np.array([
            [892.1746128870618, 0.0, 829.7903330088201],
            [0.0, 891.4721112020742, 606.9965952706247],
            [0.0, 0.0, 1.0],
        ])

        scene_distortion_coefficients = np.array([
            -0.13199101574152391,
            0.11064108837365579,
            0.00010404274838141136,
            -0.00019483441697480834,
            -0.002837744957163781,
            0.17125797998042083,
            0.05167573834059702,
            0.021300346544012465,
        ])

    else:
        calibration = recording.calibration
        scene_camera_matrix = calibration.scene_camera_matrix
        scene_distortion_coefficients = calibration.scene_distortion_coefficients

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
    print(f"Wrote {export_file}")


class GazeDataPlugin(neon_player.Plugin):
    label = "Gaze Data"

    def __init__(self) -> None:
        super().__init__()
        self.recording: Optional[NeonRecording] = None

        self._annulus_color = QColor(255, 0, 0, 128)
        self._offset_x = 0.0
        self._offset_y = 0.0

        self._visualizations: list[GazeVisualization] = [
            AnnulusViz(),
        ]

    def on_recording_loaded(self, recording: Optional[NeonRecording]) -> None:
        self.recording = recording
        for viz in self._visualizations:
            viz.on_recording_loaded(recording)

    def render(self, painter: QPainter, time_in_recording: int) -> None:
        if self.recording is None:
            return

        scene_idx = np.searchsorted(self.recording.scene.ts, time_in_recording) - 1
        if scene_idx >= len(self.recording.scene) - 1 or scene_idx < 0:
            gaze_start_ts = time_in_recording
            gaze_end_ts = gaze_start_ts + 1e9 / 30

        else:
            gaze_start_ts = self.recording.scene[scene_idx].ts
            gaze_end_ts = self.recording.scene[scene_idx + 1].ts

        after_mask = self.recording.gaze.ts >= gaze_start_ts
        before_mask = self.recording.gaze.ts < gaze_end_ts
        gazes = self.recording.gaze[after_mask & before_mask]

        for viz in self._visualizations:
            viz.render(painter, gazes, self._offset_x, self._offset_y)  # type: ignore

    @action
    def export(self, destination: Path = Path()) -> BGWorker:
        app = neon_player.instance()
        return BGWorker(
            "Export Gaze Data", bg_export, app.recording._rec_dir, destination
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
    @property_params(use_subclass_selector=True)
    def visualizations(self) -> list["GazeVisualization"]:
        return self._visualizations

    @visualizations.setter
    def visualizations(self, value: list["GazeVisualization"]) -> None:
        self._visualizations = value

        for viz in self._visualizations:
            viz.changed.connect(self.changed.emit)
            if viz.recording is None:
                viz.on_recording_loaded(self.recording)


class GazeVisualization(PersistentPropertiesMixin, QObject):
    changed = Signal()

    _known_types: ClassVar[list] = []

    def __init__(self) -> None:
        super().__init__()
        self._use_offset = True
        self.recording: Optional[NeonRecording] = None

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

    def on_recording_loaded(self, recording: Optional[NeonRecording]) -> None:
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
            center = QPointF(gaze.x + offset[0], gaze.y + offset[1])

            painter.drawEllipse(center, self._radius, self._radius)

    @property
    def color(self) -> QColor:
        return self._color

    @color.setter
    def color(self, value: QColor) -> None:
        self._color = value

    @property
    @property_params(min=1, max=9999)
    def radius(self) -> int:
        return self._radius

    @radius.setter
    def radius(self, value: int) -> None:
        self._radius = value

    @property
    @property_params(min=1, max=9999)
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
            center = QPointF(gaze.x + offset[0], gaze.y + offset[1])

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
    @property_params(min=1, max=2048)
    def size(self) -> int:
        return self._size

    @size.setter
    def size(self, value: int) -> None:
        self._size = value

    @property
    @property_params(min=1, max=2048)
    def stroke_width(self) -> int:
        return self._stroke_width

    @stroke_width.setter
    def stroke_width(self, value: int) -> None:
        self._stroke_width = value
