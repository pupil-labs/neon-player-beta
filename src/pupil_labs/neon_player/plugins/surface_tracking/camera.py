import cv2
import numpy as np
import numpy.typing as npt
from surface_tracker import Camera


class OptimalCamera(Camera):
    def __init__(
        self,
        camera_matrix: npt.ArrayLike,
        distortion_coefficients: npt.ArrayLike,
        resolution: tuple[int, int],
    ) -> None:
        super().__init__(camera_matrix, distortion_coefficients)
        self.resolution = resolution

        self.optimal_matrix, _ = cv2.getOptimalNewCameraMatrix(
            self.camera_matrix,
            self.distortion_coefficients,
            self.resolution,
            alpha=1.0,
            newImgSize=self.resolution,
        )

        self.undistortion_maps = cv2.initUndistortRectifyMap(
            self.camera_matrix,
            self.distortion_coefficients,
            None,
            self.optimal_matrix,
            self.resolution,
            cv2.CV_32FC1,
        )

        self.distortion_maps = self._build_distort_maps()

    def _build_distort_maps(self):
        w_dst, h_dst = self.resolution

        # create grid of pixel coordinates in the distorted image
        xs = np.arange(w_dst)
        ys = np.arange(h_dst)
        xv, yv = np.meshgrid(xs, ys)
        pix = np.stack((xv, yv), axis=-1).astype(np.float32)  # (h_dst, w_dst, 2)

        # Convert pixel coords (u_d, v_d) in distorted image to normalized camera
        # coords x_d = K^{-1} * [u;v;1]
        pts = pix.reshape(-1, 1, 2).astype(np.float64)

        undistorted_pts = cv2.undistortPoints(
            pts,
            self.camera_matrix,
            self.distortion_coefficients,
            R=None,
            P=self.optimal_matrix,
        )

        # undistorted_pts are pixel coordinates in the undistorted image corresponding
        # to each distorted pixel.
        map_xy = undistorted_pts.reshape(h_dst, w_dst, 2).astype(np.float32)

        return map_xy[..., 0], map_xy[..., 1]

    def undistort_points(self, points: npt.ArrayLike):
        return self._map_points(points, self.distortion_maps)

    def distort_points(self, points: npt.ArrayLike):
        return self._map_points(points, self.undistortion_maps)

    def _map_points(self, points, maps):
        points = np.asarray(points).reshape(-1, 2)
        ix = np.clip(np.round(points[:, 0]).astype(int), 0, self.resolution[0] - 1)
        iy = np.clip(np.round(points[:, 1]).astype(int), 0, self.resolution[1] - 1)

        return np.stack((maps[0][iy, ix], maps[1][iy, ix]), axis=-1)

    def undistort_image(
        self,
        img: npt.NDArray,
    ) -> npt.NDArray:
        return cv2.remap(img, *self.undistortion_maps, interpolation=cv2.INTER_LINEAR)

    def distort_image(self, img):
        distorted_img = cv2.remap(
            img,
            *self.distortion_maps,
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
        )

        return distorted_img
