import logging
import typing as T
from pathlib import Path

import mediapipe as mp
import numpy as np
import pandas as pd
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPolygonF
from qt_property_widgets.utilities import property_params

from pupil_labs.neon_player import Plugin, ProgressUpdate, action, utilities
from pupil_labs.neon_recording import NeonRecording


class FaceDetection(Plugin):
    def __init__(self):
        super().__init__()

        self.detection_job = None
        self.faces = None

        mp_drawing = mp.solutions.drawing_utils
        self.drawing_spec = mp_drawing.DrawingSpec(
            thickness=1,
            circle_radius=1,
            color=(0, 255, 0),
        )
        self._mesh_alpha = 128

        self._render_meshes = True

        self.aoi_indices = {
            "left_eye": [263, 466, 388, 387, 386, 385, 384, 398, 362, 382, 381, 380, 374, 477, 373, 390, 249],
            "right_eye": [33, 246, 161, 160, 159, 158, 157, 173, 133, 155, 154, 153, 145, 144, 163, 7],
            "mouth": [0, 267, 269, 270, 409, 291, 375, 321, 405, 314, 17, 84, 181, 91, 146, 61, 185, 40, 39, 37],
        }
        self._intersection_radius = 64

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        self.load_object_cache()

    def load_object_cache(self) -> None:
        objects_file = self.get_cache_path() / "faces.npy"

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
            "Detect Faces", "FaceDetection.bg_detect"
        )
        self.detection_job.finished.connect(self._load_object_cache)

    def render(self, painter: QPainter, time_in_recording: int) -> None:
        if not self.render_meshes:
            return

        if self.faces is None:
            return

        scene_idx = self.get_scene_idx_for_time(time_in_recording)
        if not (0 <= scene_idx < len(self.faces)):
            return

        frame_faces = self.faces[scene_idx]
        if frame_faces is None:
            return

        mp_drawing = mp.solutions.drawing_utils
        mp_face_mesh = mp.solutions.face_mesh

        overlay = np.zeros((
            self.recording.scene.height,
            self.recording.scene.width,
            3
        ), dtype=np.uint8)

        for face in frame_faces:
            mp_drawing.draw_landmarks(
                image=overlay,
                landmark_list=face,
                connections=mp_face_mesh.FACEMESH_CONTOURS,
                landmark_drawing_spec=self.drawing_spec,
                connection_drawing_spec=self.drawing_spec
            )

        alpha = np.zeros_like(overlay[:, :, 0], dtype=np.uint8)

        alpha[np.any(overlay != 0, axis=-1)] = self._mesh_alpha
        overlay_alphad = np.dstack((overlay, alpha))
        overlay_image = utilities.qimage_from_frame(overlay_alphad)

        painter.drawImage(0, 0, overlay_image)

        gaze_plugin = Plugin.get_instance_by_name("GazeDataPlugin")

        pen = painter.pen()
        pen.setWidth(5)

        for k in self.aoi_indices:
            landmarks = self.get_aoi(scene_idx, k)
            aoi_path = self.create_path_from_landmarks(landmarks)

            gazes = gaze_plugin.get_gazes_for_scene(scene_idx)
            for gaze in gazes:
                # test if the gaze is inside the polygon
                circle_path = QPainterPath()
                circle_path.addEllipse(
                    QPointF(gaze.point[0], gaze.point[1]),
                    self._intersection_radius,
                    self._intersection_radius
                )
                if circle_path.intersects(aoi_path):
                    pen.setColor(QColor(255, 0, 0))
                    break
            else:
                pen.setColor(QColor(255, 255, 255))

            painter.setPen(pen)
            painter.drawPath(aoi_path)

    def get_aoi(self, scene_idx: int, aoi_name: str) -> T.List[T.Tuple[float, float]]:
        frame_faces = self.faces[scene_idx]
        if frame_faces is None:
            return None

        indices = self.aoi_indices[aoi_name]
        return [
            (
                face.landmark[idx].x * self.recording.scene.width,
                face.landmark[idx].y * self.recording.scene.height,
            ) for face in frame_faces for idx in indices
        ]

    def _load_object_cache(self) -> None:
        objects_file = self.get_cache_path() / "faces.npy"
        if objects_file.exists():
            self.faces = np.load(str(objects_file), allow_pickle=True).tolist()

    def bg_detect(self) -> T.Generator[ProgressUpdate, None, None]:
        mp_face_mesh = mp.solutions.face_mesh
        face_mesh = mp_face_mesh.FaceMesh(
            static_image_mode=False,
            refine_landmarks=True,
            min_detection_confidence=0.15
        )

        results_by_frame = []
        for frame_idx, frame in enumerate(self.recording.scene):
            pixels = frame.bgr
            results = face_mesh.process(pixels)
            if results.multi_face_landmarks:
                logging.info(f"Detected face on frame {frame_idx}")
                results_by_frame.append(results.multi_face_landmarks)
            else:
                results_by_frame.append(None)

            yield ProgressUpdate((frame_idx + 1) / len(self.recording.scene))

        destination = self.get_cache_path() / "faces.npy"
        destination.parent.mkdir(parents=True, exist_ok=True)
        np.save(destination, np.array(results_by_frame, dtype=object))

    @action
    def export(self, destination: Path = Path()) -> None:
        gaze_plugin = Plugin.get_instance_by_name("GazeDataPlugin")

        data = {
            "scene_idx": [],
            "time": [],
        }
        for aoi_name in self.aoi_indices:
            data[aoi_name] = []

        for scene_idx, frame in enumerate(self.recording.scene):
            data["scene_idx"].append(scene_idx)
            data["time"].append(frame.time)
            for aoi_name in self.aoi_indices:
                landmarks = self.get_aoi(scene_idx, aoi_name)

                if landmarks is None:
                    data[aoi_name].append(False)
                    continue

                aoi_path = self.create_path_from_landmarks(landmarks)
                gazes = gaze_plugin.get_gazes_for_scene(scene_idx)

                for gaze in gazes:
                    # test if the gaze is inside the polygon
                    circle_path = QPainterPath()
                    circle_path.addEllipse(
                        QPointF(gaze.point[0], gaze.point[1]),
                        self._intersection_radius,
                        self._intersection_radius
                    )
                    if circle_path.intersects(aoi_path):
                        data[aoi_name].append(True)
                        break
                else:
                    data[aoi_name].append(False)

        destination_path = destination / "face_aois.csv"
        df = pd.DataFrame(data)
        df.to_csv(destination_path, index=False)
        logging.info(f"Exported {destination_path}")


    def create_path_from_landmarks(self, landmarks: list[tuple[float, float]]) -> QPainterPath:
        polygon = QPolygonF()
        for landmark in landmarks:
            polygon.append(QPointF(*landmark))

        painter_path = QPainterPath()
        painter_path.addPolygon(polygon)
        painter_path.closeSubpath()
        return painter_path

    @property
    def render_meshes(self) -> bool:
        return self._render_meshes

    @render_meshes.setter
    def render_meshes(self, value: bool) -> None:
        self._render_meshes = value
        self.changed.emit()

    @property
    @property_params(min=1, max=100)
    def mesh_line_thickness(self) -> int:
        return self.drawing_spec.thickness

    @mesh_line_thickness.setter
    def mesh_line_thickness(self, value: int) -> None:
        self.drawing_spec.thickness = value
        self.changed.emit()

    @property
    @property_params(min=1, max=100)
    def mesh_circle_radius(self) -> int:
        return self.drawing_spec.circle_radius

    @mesh_circle_radius.setter
    def mesh_circle_radius(self, value: int) -> None:
        self.drawing_spec.circle_radius = value
        self.changed.emit()

    @property
    def mesh_color(self) -> QColor:
        c = self.drawing_spec.color
        return QColor(*c)

    @mesh_color.setter
    def mesh_color(self, value: QColor) -> None:
        self.drawing_spec.color = value.getRgb()
        self.changed.emit()

    @property
    @property_params(min=0, max=255)
    def mesh_alpha(self) -> int:
        return self._mesh_alpha

    @mesh_alpha.setter
    def mesh_alpha(self, value: int) -> None:
        self._mesh_alpha = value
        self.changed.emit()

    @property
    @property_params(min=1, max=100)
    def intersection_radius(self) -> float:
        return self._intersection_radius

    @intersection_radius.setter
    def intersection_radius(self, value: float) -> None:
        self._intersection_radius = value
        self.changed.emit()