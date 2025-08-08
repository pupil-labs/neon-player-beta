import logging

import numpy as np

from pupil_labs import neon_player
from pupil_labs.neon_player import action
from pupil_labs.neon_recording import NeonRecording


class EventsPlugin(neon_player.Plugin):
    label = "Events"

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        self.events = {}

        try:
            cached_events = self.load_cached_json('events.json')
        except Exception:
            logging.exception("Failed to load events json")
            cached_events = None

        if cached_events is None:
            for event_name in self.recording.events:
                self._setup_gui_for_event(event_name.event)
                self.events[event_name.event].append(event_name.time)
        else:
            self.events = cached_events
            for name in self.events:
                self._setup_gui_for_event(name)

        for event_name in self.events:
            self._update_timeline_data(event_name)

    def on_disabled(self) -> None:
        self.remove_timeline_plot("Events")
        for event_name in self.events:
            self.remove_timeline_plot(f"Events/{event_name}")

    @action
    def create_event_type(self, event_name: str) -> None:
        if self.recording is None:
            return

        if event_name not in self.events:
            self.events[event_name] = []
            self._setup_gui_for_event(event_name)

    def _setup_gui_for_event(self, event_name: str) -> None:
        self.add_timeline_scatter(
            f"Events/{event_name}", [],
        )
        if event_name not in ['recording.begin', 'recording.end']:
            self.register_action(
                f"Timeline/Add Event/{event_name}",
                lambda: self.add_event(event_name)
            )

            self.register_data_point_action(
                f"Events/{event_name}",
                "Delete event instance",
                self.delete_event_instance
            )

    def add_event(self, event_name: str, ts: int|None = None) -> None:
        if self.recording is None:
            return

        if ts is None:
            ts = self.app.current_ts

        self.events[event_name].append(ts)
        self.save_cached_json('events.json', self.events)
        self._update_timeline_data(event_name)

    def delete_event_instance(self, timeline_name, plot_name, data_points, mouse_event) -> None:
        event_name = timeline_name.split("/", 1)[-1]
        for point in data_points:
            self.events[event_name].remove(point.pos().x())

        self.save_cached_json('events.json', self.events)
        self._update_timeline_data(event_name)

    def _update_timeline_data(self, event_name: str) -> None:
        plot_item = self.get_timeline_plot(f"Events/{event_name}")

        if len(plot_item.items) == 0:
            self.add_timeline_scatter(
                f"Events/{event_name}",
                np.array([[t, 0] for t in self.events[event_name]]),
            )
        else:
            plot_item.items[0].setData(
                np.array([[t, 0] for t in self.events[event_name]])
            )
