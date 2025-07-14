from pathlib import Path

import pandas as pd
from scipy.spatial.transform import Rotation

from pupil_labs import neon_player
from pupil_labs.neon_player import action
from pupil_labs.neon_recording import NeonRecording


class IMUPlugin(neon_player.Plugin):
    label = "IMU"

    def __init__(self) -> None:
        super().__init__()
        self.imu_data: pd.DataFrame | None = None

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        try:
            if len(recording.imu) == 0:
                return
        except AssertionError:
            return

        rotations = Rotation.from_quat(recording.imu.quaternion_wxyz, scalar_first=True)
        eulers = rotations.as_euler(seq="yxz", degrees=True)

        self.imu_data = pd.DataFrame({
            "recording id": recording.info["recording_id"],
            "timestamp [ns]": recording.imu.ts,
            "gyro x [deg/s]": recording.imu.gyro_xyz[:, 0],
            "gyro y [deg/s]": recording.imu.gyro_xyz[:, 1],
            "gyro z [deg/s]": recording.imu.gyro_xyz[:, 2],
            "acceleration x [g]": recording.imu.accel_xyz[:, 0],
            "acceleration y [g]": recording.imu.accel_xyz[:, 1],
            "acceleration z [g]": recording.imu.accel_xyz[:, 2],
            "roll [deg]": eulers[:, 0],
            "pitch [deg]": eulers[:, 1],
            "yaw [deg]": eulers[:, 2],
            "quaternion w": recording.imu.quaternion_wxyz[:, 0],
            "quaternion x": recording.imu.quaternion_wxyz[:, 1],
            "quaternion y": recording.imu.quaternion_wxyz[:, 2],
            "quaternion z": recording.imu.quaternion_wxyz[:, 3],
        })

        for euler_axis in ["roll", "pitch", "yaw"]:
            data = self.imu_data[["timestamp [ns]", f"{euler_axis} [deg]"]]
            self.app.main_window.timeline_dock.add_timeline_line(
                "IMU Euler",
                data.to_numpy().tolist(),
            )

        for gyro_axis in "xyz":
            data = self.imu_data[["timestamp [ns]", f"gyro {gyro_axis} [deg/s]"]]
            self.app.main_window.timeline_dock.add_timeline_line(
                "IMU Gyro",
                data.to_numpy().tolist(),
            )

        for acc_axis in "xyz":
            data = self.imu_data[["timestamp [ns]", f"acceleration {acc_axis} [g]"]]
            self.app.main_window.timeline_dock.add_timeline_line(
                "IMU Acceleration",
                data.to_numpy().tolist(),
            )

    @action
    def export(self, destination: Path = Path()) -> None:
        if self.imu_data is None:
            return

        export_file = destination / "imu.csv"
        self.imu_data.to_csv(export_file, index=False)
