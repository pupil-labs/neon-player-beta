from typing import Optional

import numpy as np
from PySide6.QtGui import QImage


def qimage_from_frame(frame: Optional[np.ndarray]) -> QImage:
    if frame is None:
        return QImage()

    if len(frame.shape) == 2:
        height, width = frame.shape
        channel = 1
        image_format = QImage.Format.Format_Grayscale8
    else:
        height, width, channel = frame.shape
        image_format = QImage.Format.Format_BGR888

    bytes_per_line = channel * width

    return QImage(frame.data, width, height, bytes_per_line, image_format)


def ndarray_from_qimage(image: QImage) -> np.ndarray:
    if image.isNull():
        return np.zeros((0, 0), dtype=int)

    if image.format() == QImage.Format.Format_Grayscale8:
        return np.array(image.bits()).reshape((image.height(), image.width()))

    elif image.format() == QImage.Format.Format_BGR888:
        return np.array(image.bits()).reshape((image.height(), image.width(), 3))

    return np.zeros((0, 0), dtype=int)
