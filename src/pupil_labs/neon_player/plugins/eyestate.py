import logging
from pathlib import Path

import numpy as np
import pandas as pd
from PySide6.QtGui import QColor, QIcon
from qt_property_widgets.utilities import action_params

from pupil_labs import neon_player
from pupil_labs.neon_player import GlobalPluginProperties, action
from pupil_labs.neon_recording import NeonRecording


class PlotProps:
    def __init__(self):
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
            for half in ("Top", "Bot.")
            for side in ("left", "right")
        }
        self._eyelid_aperture_plots = dict.fromkeys(("Left", "Right"), True)

    def on_plot_visibilities_changed(self, name, value):
        pass

    @property
    def pupil_diameter(self) -> dict[str, bool]:
        return self._pupil_diameter_plots

    @pupil_diameter.setter
    def pupil_diameter(self, value: dict[str, bool]) -> None:
        self._pupil_diameter_plots = value
        self.on_plot_visibilities_changed("Pupil diameter", value)

    @property
    def eyeball_center(self) -> dict[str, bool]:
        return self._eyeball_center_plots

    @eyeball_center.setter
    def eyeball_center(self, value: dict[str, bool]) -> None:
        self._eyeball_center_plots = value
        self.on_plot_visibilities_changed("Eyeball center", value)

    @property
    def optical_axis(self) -> dict[str, bool]:
        return self._optical_axis_plots

    @optical_axis.setter
    def optical_axis(self, value: dict[str, bool]) -> None:
        self._optical_axis_plots = value
        self.on_plot_visibilities_changed("Optical axis", value)

    @property
    def eyelid_angle(self) -> dict[str, bool]:
        return self._eyelid_angle_plots

    @eyelid_angle.setter
    def eyelid_angle(self, value: dict[str, bool]) -> None:
        self._eyelid_angle_plots = value
        self.on_plot_visibilities_changed("Eyelid angle", value)

    @property
    def eyelid_aperture(self) -> dict[str, bool]:
        return self._eyelid_aperture_plots

    @eyelid_aperture.setter
    def eyelid_aperture(self, value: dict[str, bool]) -> None:
        self._eyelid_aperture_plots = value
        self.on_plot_visibilities_changed("Eyelid aperture", value)


class EyestatePluginGlobalProps(PlotProps, GlobalPluginProperties):
    pass


class EyestatePlugin(PlotProps, neon_player.Plugin):
    label = "3D Eye States"
    global_properties = EyestatePluginGlobalProps()

    def __init__(self) -> None:
        PlotProps.__init__(self)
        neon_player.Plugin.__init__(self)

        self.eyestate_data = None
        self.units = {
            "Pupil diameter": "mm",
            "Eyeball center": "mm",
            "Eyelid angle": "rad",
            "Eyelid aperture": "mm",
        }

        self.color_map = {
            "left": QColor("#1f77b4"),
            "right": QColor("#d62728"),
            "left x": QColor("#1f77b4"),
            "left y": QColor("#ff7f0e"),
            "left z": QColor("#2ca02c"),
            "right x": QColor("#d62728"),
            "right y": QColor("#9467bd"),
            "right z": QColor("#8c564b"),
            "top left": QColor("#1f77b4"),
            "bottom left": QColor("#ff7f0e"),
            "top right": QColor("#d62728"),
            "bottom right": QColor("#9467bd"),
        }

    def __setstate__(self, state):
        if state != {}:
            neon_player.Plugin.__setstate__(self, state)
        else:
            app = neon_player.instance()
            super().__setstate__(
                app.settings.plugin_globals["EyestatePlugin"].to_dict()
            )

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        try:
            if len(recording.eyeball) == 0:
                return
        except AssertionError:
            return

        eyeball = recording.eyeball
        pupil = recording.pupil
        eyestate_data_dict = {
            "recording id": recording.id,
            "timestamp [ns]": eyeball.time,
            "pupil diameter left [mm]": pupil.diameter_left,
            "pupil diameter right [mm]": pupil.diameter_right,
            "eyeball center left x [mm]": eyeball.center_left[:, 0],
            "eyeball center left y [mm]": eyeball.center_left[:, 1],
            "eyeball center left z [mm]": eyeball.center_left[:, 2],
            "eyeball center right x [mm]": eyeball.center_right[:, 0],
            "eyeball center right y [mm]": eyeball.center_right[:, 1],
            "eyeball center right z [mm]": eyeball.center_right[:, 2],
            "optical axis left x": eyeball.optical_axis_left[:, 0],
            "optical axis left y": eyeball.optical_axis_left[:, 1],
            "optical axis left z": eyeball.optical_axis_left[:, 2],
            "optical axis right x": eyeball.optical_axis_right[:, 0],
            "optical axis right y": eyeball.optical_axis_right[:, 1],
            "optical axis right z": eyeball.optical_axis_right[:, 2],
        }

        try:
            eyelid = recording.eyelid
            eyelid_data = {
                "eyelid angle top left [rad]": eyelid.angle_left[:, 0],
                "eyelid angle bottom left [rad]": eyelid.angle_left[:, 1],
                "eyelid aperture left [mm]": eyelid.aperture_left,
                "eyelid angle top right [rad]": eyelid.angle_right[:, 0],
                "eyelid angle bottom right [rad]": eyelid.angle_right[:, 1],
                "eyelid aperture right [mm]": eyelid.aperture_right,
            }
            eyestate_data_dict = {**eyestate_data_dict, **eyelid_data}

        except KeyError:
            logging.warning("Eyelid data not found in recording")

        self.eyestate_data = pd.DataFrame(eyestate_data_dict)

        self._update_plot_visibilities("Pupil diameter", self._pupil_diameter_plots)
        self._update_plot_visibilities("Eyeball center", self._eyeball_center_plots)
        self._update_plot_visibilities("Optical axis", self._optical_axis_plots)
        self._update_plot_visibilities("Eyelid angle", self._eyelid_angle_plots)
        self._update_plot_visibilities("Eyelid aperture", self._eyelid_aperture_plots)

    def on_disabled(self) -> None:
        timeline = self.get_timeline()
        timeline.remove_timeline_plot("Eyestate - Pupil diameter")
        timeline.remove_timeline_plot("Eyestate - Eyeball center")
        timeline.remove_timeline_plot("Eyestate - Optical axis")
        timeline.remove_timeline_plot("Eyestate - Eyelid angle")
        timeline.remove_timeline_plot("Eyestate - Eyelid aperture")

    def on_plot_visibilities_changed(self, name, value):
        return self._update_plot_visibilities(name, value)

    def _update_plot_visibilities(
        self, group_name: str, plot_flags: dict[str, bool]
    ) -> None:
        if self.eyestate_data is None:
            return

        timeline = self.get_timeline()
        group_display_title = f"Eyestate - {group_name}"

        for plot_name, enabled in plot_flags.items():
            legend_label = plot_name.replace("Bottom ", "Bot ")
            existing_plot = timeline.get_timeline_series(
                group_display_title, legend_label
            )
            if enabled and existing_plot is None:
                # add plot
                key = f"{group_name.lower()} {plot_name.lower()}"
                if group_name in self.units:
                    key += f" [{self.units[group_name]}]"

                color = self.color_map.get(plot_name.lower(), None)

                try:
                    data = self.eyestate_data[["timestamp [ns]", key]].to_numpy()
                except KeyError:
                    logging.warning(f"{key} data not found for this recording")
                    data = np.empty((0, 2))

                timeline.add_timeline_line(
                    group_display_title, data, legend_label, color=color
                )

            elif not enabled and existing_plot is not None:
                # remove plot
                timeline.remove_timeline_series(group_display_title, legend_label)

    @action
    @action_params(compact=True, icon=QIcon(str(neon_player.asset_path("export.svg"))))
    def export(self, destination: Path = Path()) -> None:
        if self.eyestate_data is None:
            return

        export_file = destination / "3d_eye_states.csv"

        start_time, stop_time = neon_player.instance().recording_settings.export_window
        start_mask = self.eyestate_data["timestamp [ns]"] >= start_time
        stop_mask = self.eyestate_data["timestamp [ns]"] <= stop_time

        self.eyestate_data[start_mask & stop_mask].to_csv(export_file, index=False)
