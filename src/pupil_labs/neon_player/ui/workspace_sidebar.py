from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTableWidgetItem, QAbstractItemView, QHeaderView
)

from pupil_labs import neon_player
from pupil_labs.neon_player.workspace import RecordingMetadata
from pupil_labs.neon_player.ui.components import HoverRowTable
from pupil_labs.neon_recording import NeonRecording


class WorkspaceSidebar(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("WorkspaceSidebar")

        self._column_field_mapping = {
            "Recording name": ("name", None),
            "Duration": ("duration", lambda dur: str(dur)),
            "Recorded": ("recorded", lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S")),
            "Wearer": ("wearer", None)
        }
        self._column_names = list(self._column_field_mapping.keys())

        self.recordings_table = HoverRowTable(self)
        self.recordings_table.setColumnCount(len(self._column_names))
        self.recordings_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.recordings_table.setFocusPolicy(Qt.NoFocus)
        self.recordings_table.setHorizontalHeaderLabels(self._column_names)
        self.recordings_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.recordings_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.recordings_table.setShowGrid(False)
        self.recordings_table.cellClicked.connect(self.on_table_cell_clicked)

        horiz_header = self.recordings_table.horizontalHeader()
        horiz_header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        horiz_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        horiz_header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        horiz_header.setCursor(Qt.CursorShape.PointingHandCursor)

        vert_header = self.recordings_table.verticalHeader()
        vert_header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        vert_header.setVisible(False)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(QLabel("Workspace"))
        main_layout.addWidget(self.recordings_table)
        main_layout.setContentsMargins(10, 10, 10, 10)
        self.setLayout(main_layout)
        self.setMinimumSize(400, 100)

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        recording_names = [
            self.recordings_table.item(row, 0).text()
            for row in range(self.recordings_table.rowCount())
        ]
        recording_index = recording_names.index(recording._rec_dir.name)
        self.recordings_table.setCurrentCell(recording_index, 0)

    def on_table_cell_clicked(self, row: int, column: int) -> None:
        app = neon_player.instance()
        recording_name = self.recordings_table.item(row, 0).text()
        recording_path = app.workspace.get_recording_path(recording_name)
        app.load_recording(recording_path)

    def update_recording_table(self, recording_list: list[RecordingMetadata]) -> None:
        self.recordings_table.clearContents()
        self.recordings_table.setSortingEnabled(False)

        self.recordings_table.setRowCount(len(recording_list))
        for i_row, recording in enumerate(recording_list):
            for i_col, (field, formatter) in enumerate(
                self._column_field_mapping.values()
            ):
                value = getattr(recording, field)
                if formatter is not None:
                    value = formatter(value)
                self.recordings_table.setItem(i_row, i_col, QTableWidgetItem(value))

        self.recordings_table.resizeColumnsToContents()
        self.recordings_table.setSortingEnabled(True)
