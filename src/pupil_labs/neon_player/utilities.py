import typing as T

import cv2
import numpy as np
from PySide6.QtGui import QImage

from pupil_labs.neon_recording import NeonRecording


def qimage_from_frame(frame: np.ndarray | None) -> QImage:
    if frame is None:
        return QImage()

    if len(frame.shape) == 2:
        height, width = frame.shape
        channel = 1
        image_format = QImage.Format.Format_Grayscale8
    else:
        height, width, channel = frame.shape
        if channel == 3:
            image_format = QImage.Format.Format_BGR888
        else:
            image_format = QImage.Format.Format_RGBA8888

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


def get_scene_intrinsics(recording: NeonRecording) -> tuple[np.ndarray, np.ndarray]:
    if recording.calibration is None:
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

    return scene_camera_matrix, scene_distortion_coefficients
