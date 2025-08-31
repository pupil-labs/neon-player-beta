import logging
import typing as T

import mediapipe as mp
import numpy as np
from PySide6.QtGui import QColor, QPainter
from qt_property_widgets.utilities import property_params

from pupil_labs.neon_player import Plugin, ProgressUpdate, utilities
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

        scene_idx = (
            np.searchsorted(self.recording.scene.time, time_in_recording, "right") - 1
        )
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
            break

        alpha = np.zeros_like(overlay[:, :, 0], dtype=np.uint8)

        alpha[np.any(overlay != 0, axis=-1)] = self._mesh_alpha
        overlay_alphad = np.dstack((overlay, alpha))
        overlay_image = utilities.qimage_from_frame(overlay_alphad)
        painter.drawImage(0, 0, overlay_image)

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
