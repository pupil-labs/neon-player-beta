import logging
from pathlib import Path

import numpy as np
import pandas as pd
from pupil_labs.neon_recording import NeonRecording

from pupil_labs import neon_player
from pupil_labs.neon_player import GlobalPluginProperties, action


class EventsPluginGlobalProps(GlobalPluginProperties):
    def __init__(self) -> None:
        super().__init__()
        self._global_event_types: list[str] = []

    @property
    def global_event_types(self) -> list[str]:
        return self._global_event_types

    @global_event_types.setter
    def global_event_types(self, value: list[str]) -> None:
        self._global_event_types = value


class EventsPlugin(neon_player.Plugin):
    label = "Events"
    global_properties = EventsPluginGlobalProps()

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        self.events = {}

        try:
            cached_events = self.load_cached_json('events.json')
        except Exception:
            logging.exception("Failed to load events json")
            cached_events = None

        if cached_events is None:
            for event in self.recording.events:
                self._setup_gui_for_event(event.event)
                if event.event not in self.events:
                    self.events[event.event] = []

                self.events[event.event].append(event.time)
        else:
            self.events = cached_events
            for name in self.events:
                self._setup_gui_for_event(name)

        for event_name in self.events:
            self._update_timeline_data(event_name)

        for event_name in self.global_properties.global_event_types:
            if event_name not in self.events:
                self.events[event_name] = []
                self._setup_gui_for_event(event_name)

    def on_disabled(self) -> None:
        if self.recording is None:
            return

        timeline = self.get_timeline_dock()
        timeline.remove_timeline_plot("Events")
        for event_name in self.events:
            timeline.remove_timeline_plot(f"Events/{event_name}")

    @action
    def create_event_type(self, event_name: str) -> None:
        if self.recording is None:
            return

        if event_name not in self.events:
            self.events[event_name] = []
            self._setup_gui_for_event(event_name)

    def _setup_gui_for_event(self, event_name: str) -> None:
        timeline = self.get_timeline_dock()
        timeline.add_timeline_scatter(
            f"Events/{event_name}", [],
        )
        if event_name not in ['recording.begin', 'recording.end']:
            self.register_action(
                f"Timeline/Add Event/{event_name}",
                lambda: self.add_event(event_name)
            )

            self.register_data_point_action(
                f"Events/{event_name}",
                f"Delete {event_name} instance",
                lambda data_point: self.delete_event_instance(f"Events/{event_name}", data_point)
            )

        self.register_data_point_action(
            f"Events/{event_name}",
            f"Seek to this {event_name}",
            self.seek_to_event_instance
        )

    def add_event(self, event_name: str, ts: int|None = None) -> None:
        if self.recording is None:
            return

        if ts is None:
            ts = self.app.current_ts

        self.events[event_name].append(ts)
        self.save_cached_json('events.json', self.events)
        self._update_timeline_data(event_name)

    def delete_event_instance(self, timeline_name, data_point) -> None:
        event_name = timeline_name.split("/", 1)[-1]
        self.events[event_name].remove(data_point[0])

        self.save_cached_json('events.json', self.events)
        self._update_timeline_data(event_name)

    def seek_to_event_instance(self, data_point) -> None:
        self.app.seek_to(data_point[0])

    def _update_timeline_data(self, event_name: str) -> None:
        timeline = self.get_timeline_dock()
        plot_item = timeline.get_timeline_plot(f"Events/{event_name}")

        if len(plot_item.items) == 0:
            timeline.add_timeline_scatter(
                f"Events/{event_name}",
                np.array([[t, 0] for t in self.events[event_name]]),
            )
        else:
            plot_item.items[0].setData(
                np.array([[t, 0] for t in self.events[event_name]])
            )

    @action
    def export(self, destination: Path = Path(".")):
        start_time, stop_time = neon_player.instance().recording_settings.export_window
        events_df = pd.DataFrame({
            "recording id": self.recording.info["recording_id"],
            "timestamp [ns]": list(self.events.values()),
            "event": list(self.events.keys()),
        })

        events_df = events_df.explode("timestamp [ns]").reset_index(drop=True).dropna()
        events_df["timestamp [ns]"] = events_df["timestamp [ns]"].astype(
            self.recording.events.time.dtype
        )
        start_mask = (events_df["timestamp [ns]"] >= start_time)
        stop_mask = (events_df["timestamp [ns]"] <= stop_time)
        events_df = events_df[start_mask & stop_mask]
        events_df.to_csv(destination / "events.csv", index=False)
