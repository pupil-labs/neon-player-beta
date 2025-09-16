from PySide6.QtCore import QPointF
from PySide6.QtGui import QPainter
from qt_property_widgets.utilities import property_params

from pupil_labs import neon_player
from pupil_labs.neon_player.utilities import qimage_from_frame


class EyeOverlayPlugin(neon_player.Plugin):
    label = "Eye Overlay"

    def __init__(self) -> None:
        super().__init__()

        self._offset_x = 0.02
        self._offset_y = 0.02
        self._scale = 1.0
        self._opacity = 1.0

    def render(self, painter: QPainter, time_in_recording: int) -> None:
        if self.recording is None:
            return

        eye_frame = self.recording.eye.sample([time_in_recording])[0]
        if abs(time_in_recording - eye_frame.time) / 1e9 > 1 / 30:
            return

        image = qimage_from_frame(eye_frame.gray).scaled(
            int(eye_frame.width * self._scale),
            int(eye_frame.height * self._scale)
        )
        painter.setOpacity(self._opacity)
        painter.drawImage(
            QPointF(
                self._offset_x * self.recording.scene.width,
                self._offset_y * self.recording.scene.height
            ),
            image,
        )
        painter.setOpacity(1.0)

    @property
    @property_params(min=0, max=1, step=0.01, decimals=3)
    def offset_x(self) -> float:
        return self._offset_x

    @offset_x.setter
    def offset_x(self, value: float) -> None:
        self._offset_x = value

    @property
    @property_params(min=0, max=1, step=0.01, decimals=3)
    def offset_y(self) -> float:
        return self._offset_y

    @offset_y.setter
    def offset_y(self, value: float) -> None:
        self._offset_y = value

    @property
    @property_params(min=0, max=10, step=0.01, decimals=3)
    def scale(self) -> float:
        return self._scale

    @scale.setter
    def scale(self, value: float) -> None:
        self._scale = value

    @property
    @property_params(min=0, max=1, step=0.01, decimals=3)
    def opacity(self) -> float:
        return self._opacity

    @opacity.setter
    def opacity(self, value: float) -> None:
        self._opacity = value
