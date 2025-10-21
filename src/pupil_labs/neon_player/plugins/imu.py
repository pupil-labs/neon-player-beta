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

        self._show_rotation = True
        self._show_gyro = True
        self._show_acceleration = True

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        try:
            if len(recording.imu) == 0:
                return
        except AssertionError:
            return

        rotations = Rotation.from_quat(recording.imu.rotation)
        eulers = rotations.as_euler(seq="yxz", degrees=True)

        self.imu_data = pd.DataFrame({
            "recording id": recording.info["recording_id"],
            "timestamp [ns]": recording.imu.time,
            "gyro x [deg/s]": recording.imu.angular_velocity[:, 0],
            "gyro y [deg/s]": recording.imu.angular_velocity[:, 1],
            "gyro z [deg/s]": recording.imu.angular_velocity[:, 2],
            "acceleration x [g]": recording.imu.acceleration[:, 0],
            "acceleration y [g]": recording.imu.acceleration[:, 1],
            "acceleration z [g]": recording.imu.acceleration[:, 2],
            "roll [deg]": eulers[:, 0],
            "pitch [deg]": eulers[:, 1],
            "yaw [deg]": eulers[:, 2],
            "quaternion x": recording.imu.rotation[:, 0],
            "quaternion y": recording.imu.rotation[:, 1],
            "quaternion z": recording.imu.rotation[:, 2],
            "quaternion w": recording.imu.rotation[:, 3],
        })

        self.update_plots()

    def on_disabled(self) -> None:
        timeline = self.get_timeline_dock()
        for name in ["IMU - Orientation", "IMU - Gyroscope", "IMU - Acceleration"]:
            timeline.remove_timeline_plot(name)


    def update_plots(self) -> None:
        if self.imu_data is None:
            return

        timeline = self.get_timeline_dock()

        rotation_plot = timeline.get_timeline_plot("    Rotation")
        if self._show_rotation and rotation_plot is None:
            for euler_axis in ["roll", "pitch", "yaw"]:
                data = self.imu_data[["timestamp [ns]", f"{euler_axis} [deg]"]]
                timeline.add_timeline_line(
                    "IMU - Orientation",
                    data.to_numpy(),
                    euler_axis,
                )
        elif not self._show_rotation and rotation_plot is not None:
            timeline.remove_timeline_plot("IMU - Orientation")

        gyro_plot = timeline.get_timeline_plot("IMU - Gyroscope")
        if self._show_gyro and gyro_plot is None:
            for gyro_axis in "xyz":
                data = self.imu_data[["timestamp [ns]", f"gyro {gyro_axis} [deg/s]"]]
                timeline.add_timeline_line(
                    "IMU - Gyroscope",
                    data.to_numpy(),
                    gyro_axis,
            )
        elif not self._show_gyro and gyro_plot is not None:
            timeline.remove_timeline_plot("IMU - Gyroscope")

        acc_plot = timeline.get_timeline_plot("IMU - Acceleration")
        if self._show_acceleration and acc_plot is None:
            for acc_axis in "xyz":
                data = self.imu_data[["timestamp [ns]", f"acceleration {acc_axis} [g]"]]
                timeline.add_timeline_line(
                    "IMU - Acceleration",
                    data.to_numpy(),
                    acc_axis,
            )
        elif not self._show_acceleration and acc_plot is not None:
            timeline.remove_timeline_plot("IMU - Acceleration")

    @action
    def export(self, destination: Path = Path()) -> None:
        if self.imu_data is None:
            return

        start_time, stop_time = neon_player.instance().recording_settings.export_window
        start_mask = self.imu_data["timestamp [ns]"] >= start_time
        stop_mask = self.imu_data["timestamp [ns]"] <= stop_time

        export_file = destination / "imu.csv"
        self.imu_data[start_mask & stop_mask].to_csv(export_file, index=False)

    @property
    def rotation(self) -> bool:
        return self._show_rotation

    @rotation.setter
    def rotation(self, value: bool) -> None:
        self._show_rotation = value
        self.update_plots()

    @property
    def gyroscope(self) -> bool:
        return self._show_gyro

    @gyroscope.setter
    def gyroscope(self, value: bool) -> None:
        self._show_gyro = value
        self.update_plots()

    @property
    def acceleration(self) -> bool:
        return self._show_acceleration

    @acceleration.setter
    def acceleration(self, value: bool) -> None:
        self._show_acceleration = value
        self.update_plots()
