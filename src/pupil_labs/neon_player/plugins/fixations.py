import logging
import typing as T
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import numpy.typing as npt
import pandas as pd
from PySide6.QtCore import QObject, QPointF, Signal
from PySide6.QtGui import QColor, QPainter
from qt_property_widgets.utilities import PersistentPropertiesMixin, property_params

import pupil_labs.neon_recording as nr
from pupil_labs import neon_player
from pupil_labs.neon_player import action
from pupil_labs.neon_player.job_manager import ProgressUpdate
from pupil_labs.neon_player.plugins.gaze import GazeDataPlugin
from pupil_labs.neon_player.utilities import (
    cart_to_spherical,
    get_scene_intrinsics,
    unproject_points,
)
from pupil_labs.neon_recording import NeonRecording
from pupil_labs.neon_recording.stream.fixation_stream import FixationArray


def bg_optic_flow(recording_path: Path) -> T.Generator[ProgressUpdate, None, None]:
    recording = nr.open(recording_path)

    previous_frame = None
    list_delta_vec = []
    timestamps = []
    delta_time = []

    progress_total = len(recording.scene) + 10

    for frame_idx, frame in enumerate(recording.scene):
        if previous_frame is not None:
            # get optic flow vectors on a grid
            delta_vec, _, _ = calc_grid_optic_flow_LK(previous_frame.gray, frame.gray)

            # average optic flow vectors over the whole image
            delta_vec = np.nanmean(delta_vec, axis=(0, 1))

            # keep results
            list_delta_vec.append(delta_vec)
            timestamps.append(frame.ts)
            delta_time.append((frame.ts - previous_frame.ts) / 1e9)

        previous_frame = frame
        yield ProgressUpdate(frame_idx / progress_total)

    # reshape data so that first axis is time axis
    if not len(list_delta_vec):
        time_axis: np.ndarray = np.array([])
        optic_flow_x: np.ndarray = np.array([])
        optic_flow_y: np.ndarray = np.array([])

    else:
        optic_flow_LK = np.stack(list_delta_vec, 0)
        optic_flow_x = optic_flow_LK[:, 0]
        optic_flow_y = optic_flow_LK[:, 1]
        delta_time_array = np.array(delta_time).reshape(-1)

        # convert to pixels/sec
        optic_flow_x = optic_flow_x / delta_time_array
        optic_flow_y = optic_flow_y / delta_time_array

        # get time axis
        ts_array = np.array(timestamps, dtype=np.uint64)
        time_axis = (ts_array - recording.scene.ts[0]) / 1e9

    save_file = recording_path / "optic_flow_vectors.npz"
    logging.info(f"Saving optic flow vectors to {save_file}")
    with save_file.open("wb") as file_handle:
        np.savez(
            file_handle,
            timestamps=time_axis,
            optic_flow_x=optic_flow_x,
            optic_flow_y=optic_flow_y,
        )

    yield ProgressUpdate(1.0)


def bg_export(recording_path: Path, destination: Path) -> None:
    recording = nr.open(recording_path)
    fixations_only = recording.fixations[recording.fixations["event_type"] == 1]

    scene_camera_matrix, scene_distortion_coefficients = get_scene_intrinsics(recording)
    spherical_coords = cart_to_spherical(
        unproject_points(
            fixations_only.mean_gaze_xy,
            scene_camera_matrix,
            scene_distortion_coefficients,
        )
    )

    fixations = pd.DataFrame({
        "recording id": recording.info["recording_id"],
        "fixation id": 1 + np.arange(len(fixations_only)),
        "start timestamp [ns]": fixations_only.start_ts,
        "end timestamp [ns]": fixations_only.end_ts,
        "duration [ms]": (fixations_only.end_ts - fixations_only.start_ts) / 1e6,
        "fixation x [px]": fixations_only.mean_gaze_xy[:, 0],
        "fixation y [px]": fixations_only.mean_gaze_xy[:, 1],
        "azimuth [deg]": spherical_coords[2],
        "elevation [deg]": spherical_coords[1],
    })

    export_file = destination / "fixations.csv"
    fixations.to_csv(export_file, index=False)
    print(f"Wrote {export_file}")


class FixationsPlugin(neon_player.Plugin):
    label = "Fixations"

    def __init__(self) -> None:
        super().__init__()
        self.recording: Optional[NeonRecording] = None

        self._visualizations: list[FixationVisualization] = [FixationAnnulusViz()]

        self.gaze_plugin: Optional[GazeDataPlugin] = None
        self.optic_flow: T.Optional[OpticFlow] = None

    def on_recording_loaded(self, recording: Optional[NeonRecording]) -> None:
        self.recording = recording
        for viz in self._visualizations:
            viz.on_recording_loaded(recording)

        self._load_optic_flow()
        if not self.optic_flow:
            app = neon_player.instance()
            job = app.job_manager.create_job(
                "Calculate optic flow", bg_optic_flow, app.recording._rec_dir
            )
            job.finished.connect(self._load_optic_flow)

        app = neon_player.instance()

        self.fixations = recording.fixations[recording.fixations["event_type"] == 1]
        self.fixation_ids = 1 + np.arange(len(self.fixations))
        for fixation_idx, fixation in enumerate(self.fixations):
            app.main_window.timeline_dock.add_timeline_line(
                "Fixations",
                [
                    (fixation.start_ts, 0),
                    (fixation.end_ts, 0),
                ],
                f"Fixation {fixation_idx+1}"
            )

        self.saccades = recording.fixations[recording.fixations["event_type"] == 0]
        self.saccade_ids = 1 + np.arange(len(self.saccades))
        for saccade_idx, saccade in enumerate(self.saccades):
            app.main_window.timeline_dock.add_timeline_line(
                "Saccades",
                [
                    (saccade.start_ts, 0),
                    (saccade.end_ts, 0),
                ],
                f"Saccade {saccade_idx+1}"
            )

    def _load_optic_flow(self) -> None:
        if self.recording is None:
            return

        optic_flow_file = self.recording._rec_dir / "optic_flow_vectors.npz"
        if optic_flow_file.exists():
            data = np.load(optic_flow_file)
            self.optic_flow = OpticFlow(
                ts=data["timestamps"],
                x=data["optic_flow_x"],
                y=data["optic_flow_y"],
            )

    def render(self, painter: QPainter, time_in_recording: int) -> None:
        if self.recording is None:
            return

        after_mask = self.fixations["start_timestamp_ns"] <= time_in_recording
        before_mask = self.fixations["end_timestamp_ns"] > time_in_recording

        filter_mask = after_mask & before_mask
        fixations = self.fixations[filter_mask]
        fixation_ids = 1 + np.where(filter_mask)[0]

        optic_flow_offsets = []
        for fixation in fixations:  # type: ignore
            optic_flow_offset = [0, 0]

            if self.optic_flow is not None:
                start_frame_idx = self.recording.scene.ts.searchsorted(fixation.ts)
                current_frame_idx = self.recording.scene.ts.searchsorted(
                    time_in_recording
                )
                for frame_idx in range(start_frame_idx, current_frame_idx):
                    optic_flow_idx = frame_idx - 1
                    optic_frame_duration = (
                        self.optic_flow.ts[optic_flow_idx]
                        - self.optic_flow.ts[optic_flow_idx - 1]
                    )
                    optic_flow_offset[0] += (
                        self.optic_flow.x[optic_flow_idx] * optic_frame_duration
                    )
                    optic_flow_offset[1] += (
                        self.optic_flow.y[optic_flow_idx] * optic_frame_duration
                    )

            optic_flow_offsets.append(optic_flow_offset)

        for viz in self._visualizations:
            viz.render(
                painter,
                fixations,  # type: ignore
                fixation_ids,
                np.array(optic_flow_offsets),
                self.get_gaze_offset(),
            )

    def get_gaze_offset(self) -> tuple[float, float]:
        if not self.gaze_plugin:
            app = neon_player.instance()
            self.gaze_plugin = app.plugins_by_class.get("GazeDataPlugin")

        if not self.gaze_plugin:
            return (0.0, 0.0)

        return self.gaze_plugin.offset_x, self.gaze_plugin.offset_y

    @action
    def export(self, destination: Path = Path()) -> None:
        app = neon_player.instance()
        app.job_manager.create_job(
            "Export Fixations", bg_export, app.recording._rec_dir, destination
        )

    @property
    @property_params(use_subclass_selector=True, add_button_text="Add visualization")
    def visualizations(self) -> list["FixationVisualization"]:
        return self._visualizations

    @visualizations.setter
    def visualizations(self, value: list["FixationVisualization"]) -> None:
        self._visualizations = value

        for viz in self._visualizations:
            viz.changed.connect(self.changed.emit)
            if viz.recording is None:
                viz.on_recording_loaded(self.recording)


class FixationVisualization(PersistentPropertiesMixin, QObject):
    changed = Signal()

    _known_types: T.ClassVar[list] = []

    def __init__(self) -> None:
        super().__init__()
        self._use_offset = True
        self._adjust_for_optic_flow = True
        self.recording: T.Optional[NeonRecording] = None

    def render(
        self,
        painter: QPainter,
        fixations: FixationArray,
        fixation_ids: np.ndarray,
        optic_flow_offsets: np.ndarray,
        gaze_offset: tuple[float, float],
    ) -> None:
        raise NotImplementedError("Subclasses must implement this method")

    def __init_subclass__(cls: type["FixationVisualization"], **kwargs: dict) -> None:
        FixationVisualization._known_types.append(cls)

    def on_recording_loaded(self, recording: T.Optional[NeonRecording]) -> None:
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
    def adjust_for_optic_flow(self) -> bool:
        return self._adjust_for_optic_flow

    @adjust_for_optic_flow.setter
    def adjust_for_optic_flow(self, value: bool) -> None:
        self._adjust_for_optic_flow = value


class FixationAnnulusViz(FixationVisualization):
    def __init__(self) -> None:
        super().__init__()
        self._color = QColor(255, 255, 0, 196)
        self._base_radius = 50
        self._stroke_width = 5
        self._font_size = 20

    def render(
        self,
        painter: QPainter,
        fixations: FixationArray,
        fixation_ids: np.ndarray,
        optic_flow_offsets: np.ndarray,
        gaze_offset: tuple[float, float],
    ) -> None:
        if self.recording is None:
            return

        pen = painter.pen()
        pen.setWidth(self._stroke_width)
        pen.setColor(self._color)
        painter.setPen(pen)

        font = painter.font()
        font.setPointSize(self._font_size)
        painter.setFont(font)

        offset = [0.0, 0.0]

        if self._use_offset:
            if self.recording.scene.width:
                offset[0] = gaze_offset[0] * self.recording.scene.width
            if self.recording.scene.height:
                offset[1] = gaze_offset[1] * self.recording.scene.height

        for fixation_id, fixation, optic_flow_offset in zip(
            fixation_ids, fixations, optic_flow_offsets
        ):
            if self._adjust_for_optic_flow:
                center = QPointF(
                    fixation.start_gaze_xy[0] + offset[0] + optic_flow_offset[0],
                    fixation.start_gaze_xy[1] + offset[1] + optic_flow_offset[1],
                )
            else:
                center = QPointF(
                    fixation.mean_gaze_xy[0] + offset[0],
                    fixation.mean_gaze_xy[1] + offset[1],
                )

            painter.drawEllipse(center, self._base_radius, self._base_radius)
            painter.drawText(center, str(fixation_id))

    @property
    def color(self) -> QColor:
        return self._color

    @color.setter
    def color(self, value: QColor) -> None:
        self._color = value

    @property
    @property_params(min=1, max=999)
    def base_radius(self) -> int:
        return self._base_radius

    @base_radius.setter
    def base_radius(self, value: int) -> None:
        self._base_radius = value

    @property
    @property_params(min=1, max=999)
    def stroke_width(self) -> int:
        return self._stroke_width

    @stroke_width.setter
    def stroke_width(self, value: int) -> None:
        self._stroke_width = value

    @property
    @property_params(min=1, max=200)
    def font_size(self) -> int:
        return self._font_size

    @font_size.setter
    def font_size(self, value: int) -> None:
        self._font_size = value


def calc_grid_optic_flow_LK(
    previous_frame: np.ndarray,
    current_frame: np.ndarray,
    grid_spacing: int = 100,
    lk_winSize: T.Optional[tuple[int, int]] = (50, 50),
    lk_maxLevel: int = 4,
    lk_criteria: tuple[int, int, float] = (
        cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
        100,
        0.01,
    ),
) -> tuple[np.ndarray, np.ndarray, int]:
    """Calculate optic flow vector between two frames via Lucas-Kanade grid algorithm

    Args:
        previous_frame: first frame (gray)
        current_frame: second frame (gray)

        grid_spacing: spacing of the grid to be used
        lk_winSize: window size for the Lucas-Kanade algorithm (should be large enough)
        lk_maxLevel: maximum level of pyramids for the Lucas-Kanade algorithm
        lk_criteria: openCV-recursive algorithm criteria

    Returns:
        delta_vec: optic flow vectors, arranged on a grid
        coords: coordinates of the grid points
        n_quality_points: number of points for successful optic flow estimations

    """
    # define parameters for Lucas-Kanade algorithm
    lk_params = {
        "winSize": lk_winSize,
        "maxLevel": lk_maxLevel,
        "criteria": lk_criteria,
    }

    # define a grid of points to track
    X, Y = np.meshgrid(
        np.arange(grid_spacing // 2, previous_frame.shape[0], grid_spacing),
        np.arange(grid_spacing // 2, previous_frame.shape[1], grid_spacing),
    )
    p_0 = (
        np.vstack((X.flatten(), Y.flatten())).T.reshape(-1, 1, 2).astype(np.float32)
    )  # format coordinates as required for openCV
    coords = np.dstack([X, Y])  # format coordinates as (NxMx2)-matrix

    # trace points using the Lucas-Kanade algorithm
    p_1, st, _ = cv2.calcOpticalFlowPyrLK(  # type: ignore
        previous_frame, current_frame, p_0, None, **lk_params
    )

    # set all points which could not be successfully traces to NaN
    p_1[st == 0] = np.nan  # these are the new locations of the points
    p_0[st == 0] = np.nan

    # rearrange back to 2D grid
    p_1 = np.dstack([p_1[:, 0, 0].reshape(X.shape), p_1[:, 0, 1].reshape(X.shape)])
    p_0b = np.dstack([p_0[:, 0, 0].reshape(X.shape), p_0[:, 0, 1].reshape(X.shape)])

    # get difference vectors for each position
    delta_vec = p_1 - p_0b

    n_quality_points = st.sum()  # number of points that could be successfully traced
    if n_quality_points < 1:  # return only zeros if no points could be traced at all
        delta_vec = np.zeros((*X.shape, 2))

    return delta_vec, coords, n_quality_points


class LKParams(T.NamedTuple):
    """Params for cv2.calcOpticalFlowPyrLK"""

    grid_spacing: int = 100  # spacing of the grid to be used
    win_size: tuple[int, int] = (50, 50)  # window size for the Lucas-Kanade algorithm
    max_level: int = 4  # maximum level of pyramids for the Lucas-Kanade algorithm
    criteria: tuple[int, int, float] = (  # openCV-recursive algorithm criteria
        cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
        100,
        0.01,
    )


class OpticFlow(T.NamedTuple):
    ts: npt.NDArray[np.int64]
    x: npt.NDArray[np.float32]
    y: npt.NDArray[np.float32]
