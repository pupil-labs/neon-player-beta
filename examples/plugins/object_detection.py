import typing as T
from enum import Enum

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from qt_property_widgets.utilities import property_params
from ultralytics import YOLO

from pupil_labs import neon_player
from pupil_labs.neon_player import ProgressUpdate
from pupil_labs.neon_recording import NeonRecording


class DetectionModel(Enum):
    YOLO11N_SEG = "yolo11n-seg"
    YOLO11M_SEG = "yolo11m-seg"
    YOLO11X_SEG = "yolo11x-seg"


class ObjectDetection(neon_player.Plugin):
    label = "Object Detection"

    def __init__(self):
        super().__init__()
        self.gens = None

        self._model = DetectionModel.YOLO11N_SEG
        self._min_confidence = 0.5
        self._segment_color = QColor(Qt.GlobalColor.red)
        self._font = QFont("Arial", 12)

        self.detection_job = None

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        self.load_object_cache()

    def load_object_cache(self) -> None:
        objects_file = self.get_cache_path() / f"objects-{self.model.value}.npy"

        if objects_file.exists():
            self._load_object_cache()
            return

        if self.app.headless:
            self.bg_detect()
            self._load_object_cache()
            return

        if self.detection_job is not None:
            return

        self.detection_job = self.job_manager.run_background_action(
            "Detect objects", "ObjectDetection.bg_detect"
        )
        self.detection_job.finished.connect(self._load_object_cache)

    def _load_object_cache(self) -> None:
        self.detection_job = None
        objects_file = self.get_cache_path() / f"objects-{self.model.value}.npy"
        if objects_file.exists():
            self.gens = np.load(str(objects_file), allow_pickle=True).tolist()

    def render(self, painter: QPainter, time_in_recording: int) -> None:
        if self.gens is None:
            return

        scene_idx = (
            np.searchsorted(self.recording.scene.time, time_in_recording, "right") - 1
        )
        if not (0 <= scene_idx < len(self.gens)):
            return

        painter.setFont(self._font)

        results_for_frame = self.gens[scene_idx]
        for result in results_for_frame:
            if result["confidence"] < self.min_confidence:
                continue

            polygon = result["polygon"]
            path = QPainterPath()
            path.moveTo(*polygon[0])
            for point in polygon[1:]:
                path.lineTo(*point)

            path.closeSubpath()

            painter.setPen(QPen(self.segment_color, 2, Qt.PenStyle.SolidLine))
            painter.fillPath(path, QBrush(self.segment_color))

            # Prepare text
            label = f'{result["class"]} ({result["confidence"]:.2f})'
            top_left_point = polygon[0]
            painter.drawText(top_left_point[0], top_left_point[1] - 10, label)

    def bg_detect(self) -> T.Generator[ProgressUpdate, None, None]:
        detect_objects = YOLO(
            f"{self.model.value}.pt",
            verbose=False,
        )

        results_by_frame = []
        for frame_idx, frame in enumerate(self.recording.scene):
            pixels = frame.bgr
            results = detect_objects(pixels, show=False, verbose=False)[0]  # get first result

            serializable_results = []
            if results.masks is not None:
                for xy_polygon, conf, cls in zip(
                    results.masks.xy,
                    results.boxes.conf,
                    results.boxes.cls,
                    strict=True
                ):
                    serializable_results.append({
                        "polygon": xy_polygon.tolist(),
                        "confidence": conf.item(),
                        "class": results.names[cls.item()],
                    })

            results_by_frame.append(serializable_results)

            progress = (frame_idx + 1) / len(self.recording.scene)
            yield ProgressUpdate(progress)

        destination = self.get_cache_path() / f"objects-{self.model.value}.npy"
        destination.parent.mkdir(parents=True, exist_ok=True)
        np.save(destination, np.array(results_by_frame, dtype=object))

    @property
    def model(self) -> DetectionModel:
        return self._model

    @model.setter
    def model(self, value: DetectionModel) -> None:
        self._model = value
        if self.detection_job is not None:
            self.detection_job.cancel()
            self.detection_job = None

        self.load_object_cache()

    @property
    @property_params(min=0, max=1, step=0.05)
    def min_confidence(self) -> float:
        return self._min_confidence

    @min_confidence.setter
    def min_confidence(self, value: float) -> None:
        self._min_confidence = value

    @property
    def segment_color(self) -> QColor:
        return self._segment_color

    @segment_color.setter
    def segment_color(self, value: QColor) -> None:
        self._segment_color = value

    @property
    def font(self) -> QFont:
        return self._font

    @font.setter
    def font(self, value: QFont) -> None:
        self._font = value
