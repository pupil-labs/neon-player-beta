
from pupil_labs import neon_player
from pupil_labs.neon_player import action
from pupil_labs.neon_recording import NeonRecording


class EventsPlugin(neon_player.Plugin):
    label = "Events"

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        self.add_timeline_scatter(
            "Events",
            [(event.time, 0) for event in self.recording.events],
        )
        events_by_name: dict[str, list[int]] = {}

        for event in self.recording.events:
            event_name = str(event.event)
            if event_name not in events_by_name:
                events_by_name[event_name] = []

            events_by_name[event_name].append(int(event.time))

        for event_name, timestamps in events_by_name.items():
            self.add_timeline_scatter(
                f"Events/{event_name}",
                [(ts, 0) for ts in timestamps],
            )

            if event_name not in ['recording.begin', 'recording.end']:
                self.add_dynamic_action(
                    f"add_{event_name}",
                    lambda self, evt=event_name: self.add_event(evt),
                )

        self.recorded_events = events_by_name
        self.deleted_events: dict[str, list[int]] = {}
        self.added_events: dict[str, list[int]] = {}

        self.event_names = list(events_by_name.keys()) + list(self.added_events.keys())

    def on_disabled(self) -> None:
        self.remove_timeline_plot("Events")
        for event_name in self.event_names:
            self.remove_timeline_plot(f"Events/{event_name}")

    @action
    def create_event_type(self, event_name: str) -> None:
        if self.recording is None:
            return

        if event_name not in self.event_names:
            self.event_names.append(event_name)
            self.add_timeline_scatter(
                f"Events/{event_name}", [],
            )

            self.register_timeline_action(f"Add Event/{event_name}", lambda: self.add_event(event_name))

    def add_event(self, event_name: str) -> None:
        if self.recording is None:
            return

        self.add_timeline_scatter(
            f"Events/{event_name}",
            [(self.app.current_ts, 0)],
        )

        self.add_timeline_scatter(
            "Events", [(self.app.current_ts, 0)],
        )

