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
    label = "Fixations & Saccades"

    def __init__(self) -> None:
        super().__init__()

        self._visualizations: list[FixationVisualization] = [FixationCircleViz()]

        self.gaze_plugin: GazeDataPlugin | None = None
        self.optic_flow_offsets: np.ndarray | None = None
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
        if self.optic_flow_offsets is None and not self.app.headless:
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

        optic_flow_file = self.get_cache_path() / "optic_flow_offsets.npz"
        if optic_flow_file.exists():
            self.optic_flow_offsets = np.load(optic_flow_file)["offsets"]

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

        scene_idx = self.get_scene_idx_for_time(time_in_recording)

        offset = np.array([0, 0]) if self.optic_flow_offsets is None else self.optic_flow_offsets[scene_idx]

        for viz in self._visualizations:
            viz.render(
                painter,
                fixations,
                fixation_ids,
                offset,
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

    def get_export_fixations(self) -> pd.DataFrame:
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

    def get_export_saccades(self) -> pd.DataFrame:
        start_time, stop_time = neon_player.instance().recording_settings.export_window
        start_mask = self.recording.saccades.stop_time > start_time
        stop_mask = self.recording.saccades.start_time < stop_time

        saccades_ids = np.arange(len(self.recording.saccades)) + 1

        saccades = self.recording.saccades[start_mask & stop_mask]
        saccade_ids = saccades_ids[start_mask & stop_mask]

        export_data = pd.DataFrame({
            "recording id": self.recording.info["recording_id"],
            "saccade id": saccade_ids,
            "start timestamp [ns]": saccades.start_time,
            "end timestamp [ns]": saccades.stop_time,
            "duration [ms]": (saccades.stop_time - saccades.start_time) / 1e6,
            "amplitude [deg]": saccades.amplitude,
            "mean velocity [px/s]": saccades.mean_velocity,
            "peak velocity [px/s]": saccades.max_velocity,
        })

        return export_data

    @action
    @action_params(compact=True, icon=QIcon(str(neon_player.asset_path("export.svg"))))
    def export(self, destination: Path = Path()) -> None:
        export_fixations = self.get_export_fixations()

        export_file = destination / "fixations.csv"
        export_fixations.to_csv(export_file, index=False)
        logging.info(f"Exported fixations to '{export_file}'")

        export_saccades = self.get_export_saccades()

        export_file = destination / "saccades.csv"
        export_saccades.to_csv(export_file, index=False)
        logging.info(f"Exported saccades to '{export_file}'")

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

        offsets_by_frame_idx = {}
        gaze = recording.gaze

        fidx = 0
        for fixation in recording.fixations:
            fidx += 1
            gaze_samples = gaze[
                (fixation.start_time <= gaze.time) & (gaze.time <= fixation.stop_time)
            ]

            # Pick the gaze at the temporal center of the fixation as the reference
            ref_gaze = gaze_samples[len(gaze_samples) // 2]

            # Now calculate how that reference points moves throughout the fixation
            start_scene_idx, stop_scene_idx = np.searchsorted(
                recording.scene.time, [fixation.start_time, fixation.stop_time]
            )
            scene_frames = recording.scene[start_scene_idx:stop_scene_idx]

            if len(scene_frames) == 0:
                continue

            scene_frames_ts = [f.time for f in scene_frames]
            diff = np.abs(np.array(scene_frames_ts) - ref_gaze.time)
            if np.min(diff) > 100 * 1e6:
                continue

            idx = int(np.argmin(diff))
            ref_scene_img = scene_frames[idx].gray

            if ref_scene_img is None:
                continue

            # First work backwards for the first half of gaze points
            point = ref_gaze.point
            scene_image = ref_scene_img.copy()
            for next_scene_frame in reversed(scene_frames[:idx]):
                next_scene_img = next_scene_frame.gray
                next_point = calc_optic_flow(
                    scene_image,
                    next_scene_img,
                    point,
                )
                offsets_by_frame_idx[next_scene_frame.index] = ref_gaze.point - next_point

                point = next_point
                scene_image = next_scene_img

            # Now work forwards for the second half of gaze points
            point = ref_gaze.point
            scene_image = ref_scene_img.copy()
            for next_scene_frame in scene_frames[idx + 1:]:
                next_scene_img = next_scene_frame.gray
                next_point = calc_optic_flow(
                    scene_image,
                    next_scene_img,
                    point,
                )
                offsets_by_frame_idx[next_scene_frame.index] = point - next_point

                point = next_point
                scene_image = next_scene_img

            yield ProgressUpdate(next_scene_frame.index / len(recording.scene))

        offsets_by_frame_idx_arr = []
        for frame_idx in range(len(recording.scene)):
            if frame_idx in offsets_by_frame_idx:
                offsets_by_frame_idx_arr.append(offsets_by_frame_idx[frame_idx])
            else:
                offsets_by_frame_idx_arr.append(np.array([0, 0]))

        save_file = self.get_cache_path() / "optic_flow_offsets.npz"
        logging.info(f"Saving optic flow offsets to {save_file}")
        save_file.parent.mkdir(parents=True, exist_ok=True)
        with save_file.open("wb") as file_handle:
            np.savez(
                file_handle,
                offsets=offsets_by_frame_idx_arr
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
        optic_flow_offset: np.ndarray,
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

        for fixation_id, fixation in zip(
            fixation_ids, fixations, strict=True
        ):
            if self._adjust_for_optic_flow:
                center = QPointF(
                    fixation.mean_gaze_point[0] + offset[0] - optic_flow_offset[0],
                    fixation.mean_gaze_point[1] + offset[1] - optic_flow_offset[1],
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


def calc_optic_flow(
    previous_frame: np.ndarray,
    current_frame: np.ndarray,
    points: np.ndarray,
    lk_winSize: tuple[int, int] | None = (90, 90),
    lk_maxLevel: int = 3,
    lk_criteria: tuple[int, int, float] = (
        cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
        20,
        0.03,
    ),
    lk_min_eig_threshold: float = 0.005,
) -> tuple[np.ndarray, np.ndarray, int]:

    # define parameters for Lucas-Kanade algorithm
    lk_params = {
        "winSize": lk_winSize,
        "maxLevel": lk_maxLevel,
        "criteria": lk_criteria,
        "minEigThreshold": lk_min_eig_threshold,
    }

    # trace points using the Lucas-Kanade algorithm
    corrected_points, status, err = cv2.calcOpticalFlowPyrLK(  # type: ignore
        previous_frame, current_frame, points.reshape([-1, 1, 2]), None, **lk_params
    )
    return corrected_points.reshape(points.shape)


class OpticFlow(T.NamedTuple):
    ts: npt.NDArray[np.int64]
    x: npt.NDArray[np.float32]
    y: npt.NDArray[np.float32]
