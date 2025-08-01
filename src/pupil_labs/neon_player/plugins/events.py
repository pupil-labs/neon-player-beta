import logging

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
            for event in self.recording.events:
                self._add_event(event.event, event.time)
        else:
            for name, tss in cached_events.items():
                self._add_event(name, tss)

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
            self.add_timeline_scatter(
                f"Events/{event_name}", [],
            )

            self.register_timeline_action(f"Add Event/{event_name}", lambda: self.add_event(event_name))

    def _add_event(self, event_name: str, ts: list[int]|int) -> None:
        if self.recording is None:
            return

        if not isinstance(ts, list):
            ts = [ts]

        self.add_timeline_scatter(
            "Events", [(t, 0) for t in ts],
        )

        self.add_timeline_scatter(
            f"Events/{event_name}",
            [(t, 0) for t in ts],
        )

        if event_name not in self.events:
            self.events[event_name] = []
            if event_name not in ['recording.begin', 'recording.end']:
                self.register_timeline_action(
                    f"Add Event/{event_name}",
                    lambda: self.add_event(event_name)
                )

        self.events[event_name].extend(ts)

    def add_event(self, event_name: str, ts: int|None = None) -> None:
        if self.recording is None:
            return

        if ts is None:
            ts = self.app.current_ts

        self._add_event(event_name, ts)
        self.save_cached_json('events.json', self.events)
