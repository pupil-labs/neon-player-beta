from pathlib import Path

import pandas as pd
from scipy.spatial.transform import Rotation

from pupil_labs import neon_player
from pupil_labs.neon_player import action
from pupil_labs.neon_recording import NeonRecording


class EyestatePlugin(neon_player.Plugin):
    label = "Eyestate"

    def __init__(self) -> None:
        super().__init__()
        self._pupil_diameter_plots = dict.fromkeys(("Left", "Right"), True)
        self._eyeball_center_plots = {
            f"{side} {component}": True
            for side in ("Left", "Right")
            for component in "xyz"
        }
        self._optical_axis_plots = {
            f"{side} {component}": True
            for side in ("Left", "Right")
            for component in "xyz"
        }
        self._eyelid_angle_plots = {
            f"{half} {side}": True
            for half in ("Top", "Bottom")
            for side in ("Left", "Right")
        }
        self._eyelid_aperture_plots = dict.fromkeys(("Left", "Right"), True)
        self.eyestate_data = None
        self.units = {
            "Pupil diameter": "mm",
            "Eyeball center": "mm",
            "Optical axis": "mm",
            "Eyelid angle": "rad",
            "Eyelid aperture": "mm",
        }

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        try:
            if len(recording.eyeball) == 0:
                return
        except AssertionError:
            return

        eyeball = recording.eyeball
        pupil = recording.pupil
        eyelid = recording.eyelid
        self.eyestate_data = pd.DataFrame({
            "timestamp [ns]": eyeball.time,
            "pupil diameter left [mm]": pupil.diameter_left,
            "pupil diameter right [mm]": pupil.diameter_right,
            "eyeball center left x [mm]": eyeball.center_left[:, 0],
            "eyeball center left y [mm]": eyeball.center_left[:, 1],
            "eyeball center left z [mm]": eyeball.center_left[:, 2],
            "eyeball center right x [mm]": eyeball.center_right[:, 0],
            "eyeball center right y": eyeball.center_right[:, 1],
            "eyeball center right z": eyeball.center_right[:, 2],
            "optical axis left x": eyeball.optical_axis_left[:, 0],
            "optical axis left y": eyeball.optical_axis_left[:, 1],
            "optical axis left z": eyeball.optical_axis_left[:, 2],
            "optical axis right x": eyeball.optical_axis_right[:, 0],
            "optical axis right y": eyeball.optical_axis_right[:, 1],
            "optical axis right z": eyeball.optical_axis_right[:, 2],
            "eyelid angle top left [rad]": eyelid.angle_left[:, 0],
            "eyelid angle bottom left [rad]": eyelid.angle_left[:, 1],
            "eyelid aperture left [mm]": eyelid.aperture_left,
            "eyelid angle top right [rad]": eyelid.angle_right[:, 0],
            "eyelid angle bottom right [rad]": eyelid.angle_right[:, 1],
            "eyelid aperture right [mm]": eyelid.aperture_right,
        })

        self._update_plot_visibilities("Pupil diameter", self._pupil_diameter_plots)
        self._update_plot_visibilities("Eyeball center", self._eyeball_center_plots)
        self._update_plot_visibilities("Optical axis", self._optical_axis_plots)
        self._update_plot_visibilities("Eyelid angle", self._eyelid_angle_plots)
        self._update_plot_visibilities("Eyelid aperture", self._eyelid_aperture_plots)

    def on_disabled(self) -> None:
        pass

    def _update_plot_visibilities(
        self,
        group_name: str,
        plot_flags: dict[str, bool]
    ) -> None:
        if self.eyestate_data is None:
            return

        for plot_name, enabled in plot_flags.items():
            existing_plot = self.get_timeline_series(group_name, plot_name)
            if enabled and existing_plot is None:
                # add plot
                key = f"{group_name.lower()} {plot_name.lower()}"
                if group_name in self.units:
                    key += f" [{self.units[group_name]}]"

                data = self.eyestate_data[["timestamp [ns]", key]].to_numpy()
                self.add_timeline_line(group_name, data, plot_name)

            elif not enabled and existing_plot is not None:
                # remove plot
                self.remove_timeline_series(group_name, plot_name)

    @action
    def export(self, destination: Path = Path()) -> None:
        if self.eyestate_data is None:
            return

        export_file = destination / "eyestate.csv"
        self.eyestate_data.to_csv(export_file, index=False)

    @property
    def pupil_diameter(self) -> dict[str, bool]:
        return self._pupil_diameter_plots

    @pupil_diameter.setter
    def pupil_diameter(self, value: dict[str, bool]) -> None:
        self._pupil_diameter_plots = value
        self._update_plot_visibilities("Pupil diameter", value)

    @property
    def eyeball_center(self) -> dict[str, bool]:
        return self._eyeball_center_plots

    @eyeball_center.setter
    def eyeball_center(self, value: dict[str, bool]) -> None:
        self._eyeball_center_plots = value
        self._update_plot_visibilities("Eyeball center", value)

    @property
    def optical_axis(self) -> dict[str, bool]:
        return self._optical_axis_plots

    @optical_axis.setter
    def optical_axis(self, value: dict[str, bool]) -> None:
        self._optical_axis_plots = value
        self._update_plot_visibilities("Optical axis", value)

    @property
    def eyelid_angle(self) -> dict[str, bool]:
        return self._eyelid_angle_plots

    @eyelid_angle.setter
    def eyelid_angle(self, value: dict[str, bool]) -> None:
        self._eyelid_angle_plots = value
        self._update_plot_visibilities("Eyelid angle", value)

    @property
    def eyelid_aperture(self) -> dict[str, bool]:
        return self._eyelid_aperture_plots

    @eyelid_aperture.setter
    def eyelid_aperture(self, value: dict[str, bool]) -> None:
        self._eyelid_aperture_plots = value
        self._update_plot_visibilities("Eyelid aperture", value)
