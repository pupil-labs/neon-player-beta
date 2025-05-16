import logging
import typing as T

import numpy as np
from PySide6.QtCore import QObject, QPointF, Signal
from PySide6.QtGui import QColor, QPainter
from qt_property_widgets.utilities import PersistentPropertiesMixin, property_params

from pupil_labs.neon_recording import NeonRecording
from pupil_labs.neon_recording.stream.gaze_stream import GazeArray


