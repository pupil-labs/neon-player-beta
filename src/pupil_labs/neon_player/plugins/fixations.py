import logging
import typing as T
from pathlib import Path

import cv2
import numpy as np
import numpy.typing as npt
import pandas as pd
from PySide6.QtCore import QKeyCombination, QObject, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter
from qt_property_widgets.utilities import (
    PersistentPropertiesMixin,
    action_params,
    property_params,
)

from pupil_labs import neon_player
from pupil_labs.neon_player import action
from pupil_labs.neon_player.job_manager import ProgressUpdate
from pupil_labs.neon_player.plugins.gaze import GazeDataPlugin
from pupil_labs.neon_player.ui import ListPropertyAppenderAction
from pupil_labs.neon_player.utilities import (
    cart_to_spherical,
    get_scene_intrinsics,
    unproject_points,
)
from pupil_labs.neon_recording import NeonRecording
from pupil_labs.neon_recording.timeseries import FixationTimeseries


class FixationsPlugin(neon_player.Plugin):
    label = "Fixations"

    def __init__(self) -> None:
        super().__init__()

        self._visualizations: list[FixationVisualization] = [FixationCircleViz()]

        self.gaze_plugin: GazeDataPlugin | None = None
        self.optic_flow: OpticFlow | None = None
        self.header_action = ListPropertyAppenderAction("visualizations", "+ Add viz")

    def seek_by_fixation(self, direction: int) -> None:
        if len(self.recording.fixations) == 0:
            return

        fixations_up_to_now = self.recording.fixations[
            self.recording.fixations.start_time <= self.app.current_ts
        ]

        current_idx = len(fixations_up_to_now) - 1
        idx = max(0, min(len(self.recording.fixations) - 1, current_idx + direction))
        self.app.seek_to(self.recording.fixations.start_time[idx])

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        for viz in self._visualizations:
            viz.on_recording_loaded(recording)

        if len(recording.fixations) == 0:
            return

        self._load_optic_flow()
        if not self.optic_flow and not self.app.headless:
            job = self.job_manager.run_background_action(
                "Calculate optic flow", "FixationsPlugin.bg_optic_flow"
            )
            job.finished.connect(self._load_optic_flow)

        self.fixations = recording.fixations

        self.get_timeline().add_timeline_broken_bar(
            "Fixations", self.fixations[["start_time", "stop_time"]]
        )

        self.register_action(
            "Playback/Next Fixation",
            QKeyCombination(Qt.Key.Key_S),
            lambda: self.seek_by_fixation(1),
        )
        self.register_action(
            "Playback/Previous Fixation",
            QKeyCombination(Qt.Key.Key_A),
            lambda: self.seek_by_fixation(-1),
        )

    def _load_optic_flow(self) -> None:
        if self.recording is None:
            return

        optic_flow_file = self.get_cache_path() / "optic_flow_vectors.npz"
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

        if not hasattr(self, "fixations"):
            return

        after_mask = self.fixations.start_time <= time_in_recording
        before_mask = self.fixations.stop_time > time_in_recording

        filter_mask = after_mask & before_mask
        fixations = self.fixations[filter_mask]
        fixation_ids = 1 + np.where(filter_mask)[0]

        optic_flow_offsets = []
        for fixation in fixations:
            optic_flow_offset = [0, 0]

            if self.optic_flow is not None:
                start_frame_idx = self.recording.scene.time.searchsorted(
                    fixation.start_time
                )
                current_frame_idx = self.recording.scene.time.searchsorted(
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
                fixations,
                fixation_ids,
                np.array(optic_flow_offsets),
                self.get_gaze_offset(),
            )

    def get_gaze_offset(self) -> tuple[float, float]:
        if not self.gaze_plugin:
            self.gaze_plugin = neon_player.Plugin.get_instance_by_name("GazeDataPlugin")

        if not self.gaze_plugin:
            return (0.0, 0.0)

        return self.gaze_plugin.offset_x, self.gaze_plugin.offset_y

    def on_disabled(self) -> None:
        self.get_timeline().remove_timeline_plot("Fixations")
        self.unregister_action("Playback/Next Fixation")
        self.unregister_action("Playback/Previous Fixation")

    def get_export_data(self) -> pd.DataFrame:
        start_time, stop_time = neon_player.instance().recording_settings.export_window
        start_mask = self.recording.fixations.stop_time > start_time
        stop_mask = self.recording.fixations.start_time < stop_time

        fixations_ids = np.arange(len(self.recording.fixations)) + 1

        fixations = self.recording.fixations[start_mask & stop_mask]
        fixation_ids = fixations_ids[start_mask & stop_mask]

        offset = self.get_gaze_offset()
        offset *= np.array([self.recording.scene.width, self.recording.scene.height])

        offset_means = fixations.mean_gaze_point + offset

        scene_camera_matrix, scene_distortion_coefficients = get_scene_intrinsics(
            self.recording
        )
        spherical_coords = cart_to_spherical(
            unproject_points(
                offset_means,
                scene_camera_matrix,
                scene_distortion_coefficients,
            )
        )

        export_data = pd.DataFrame({
            "recording id": self.recording.info["recording_id"],
            "fixation id": fixation_ids,
            "start timestamp [ns]": fixations.start_time,
            "end timestamp [ns]": fixations.stop_time,
            "duration [ms]": (fixations.stop_time - fixations.start_time) / 1e6,
            "fixation x [px]": offset_means[:, 0],
            "fixation y [px]": offset_means[:, 1],
            "azimuth [deg]": spherical_coords[2],
            "elevation [deg]": spherical_coords[1],
        })

        return export_data

    @action
    @action_params(compact=True, icon=QIcon.fromTheme("document-save"))
    def export(self, destination: Path = Path()) -> None:
        export_data = self.get_export_data()

        export_file = destination / "fixations.csv"
        export_data.to_csv(export_file, index=False)
        logging.info(f"Exported fixations to '{export_file}'")

    @property
    @property_params(
        use_subclass_selector=True,
        prevent_add=True,
        item_params={"label_field": "label"},
        primary=True,
    )
    def visualizations(self) -> list["FixationVisualization"]:
        return self._visualizations

    @visualizations.setter
    def visualizations(self, value: list["FixationVisualization"]) -> None:
        self._visualizations = value

        for viz in self._visualizations:
            viz.changed.connect(self.changed.emit)
            if self.recording is not None:
                viz.on_recording_loaded(self.recording)

    def bg_optic_flow(self) -> T.Generator[ProgressUpdate, None, None]:
        recording = self.app.recording

        previous_frame = None
        list_delta_vec = []
        timestamps = []
        delta_time = []

        progress_total = len(recording.scene) + 10

        for frame_idx, frame in enumerate(recording.scene):
            if previous_frame is not None:
                # get optic flow vectors on a grid
                delta_vec, _, _ = calc_grid_optic_flow_LK(
                    previous_frame.gray, frame.gray
                )

                # average optic flow vectors over the whole image
                delta_vec = np.nanmean(delta_vec, axis=(0, 1))

                # keep results
                list_delta_vec.append(delta_vec)
                timestamps.append(frame.time)
                delta_time.append((frame.time - previous_frame.time) / 1e9)

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
            time_axis = (ts_array - recording.scene.time[0]) / 1e9

        save_file = self.get_cache_path() / "optic_flow_vectors.npz"
        logging.info(f"Saving optic flow vectors to {save_file}")
        save_file.parent.mkdir(parents=True, exist_ok=True)
        with save_file.open("wb") as file_handle:
            np.savez(
                file_handle,
                timestamps=time_axis,
                optic_flow_x=optic_flow_x,
                optic_flow_y=optic_flow_y,
            )

        yield ProgressUpdate(1.0)


class FixationVisualization(PersistentPropertiesMixin, QObject):
    changed = Signal()

    _known_types: T.ClassVar[list] = []

    def __init__(self) -> None:
        super().__init__()
        self._use_offset = True
        self._adjust_for_optic_flow = True
        self.recording: NeonRecording | None = None

    def render(
        self,
        painter: QPainter,
        fixations: FixationTimeseries,
        fixation_ids: np.ndarray,
        optic_flow_offsets: np.ndarray,
        gaze_offset: tuple[float, float],
    ) -> None:
        raise NotImplementedError("Subclasses must implement this method")

    def __init_subclass__(cls: type["FixationVisualization"], **kwargs: dict) -> None:
        FixationVisualization._known_types.append(cls)

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
    def adjust_for_optic_flow(self) -> bool:
        return self._adjust_for_optic_flow

    @adjust_for_optic_flow.setter
    def adjust_for_optic_flow(self, value: bool) -> None:
        self._adjust_for_optic_flow = value


class FixationCircleViz(FixationVisualization):
    label = "Circle"

    def __init__(self) -> None:
        super().__init__()
        self._color = QColor(255, 255, 0, 196)
        self._base_radius = 50
        self._stroke_width = 5
        self._font_size = 20

    def render(
        self,
        painter: QPainter,
        fixations: FixationTimeseries,
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
            fixation_ids, fixations, optic_flow_offsets, strict=True
        ):
            if self._adjust_for_optic_flow:
                center = QPointF(
                    fixation.start_gaze_point[0] + offset[0] + optic_flow_offset[0],
                    fixation.start_gaze_point[1] + offset[1] + optic_flow_offset[1],
                )
            else:
                center = QPointF(
                    fixation.mean_gaze_point[0] + offset[0],
                    fixation.mean_gaze_point[1] + offset[1],
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
    lk_winSize: tuple[int, int] | None = (50, 50),
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
