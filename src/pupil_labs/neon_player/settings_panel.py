import typing as T

from PySide6.QtCore import (
    Qt,
)
from PySide6.QtWidgets import (
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qt_property_widgets.widgets import PropertyForm

from pupil_labs import neon_player
from pupil_labs.neon_player import Plugin
from pupil_labs.neon_player.expander import Expander


class SettingsPanel(QWidget):
    # @TODO make this scrollable
    def __init__(self, parent: T.Optional[QWidget] = None) -> None:
        super().__init__(parent=parent)

        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setMinimumSize(350, 100)

        container = QWidget()
        self.container_layout = QVBoxLayout(container)
        self.container_layout.setSpacing(0)
        self.container_layout.setContentsMargins(5, 5, 5, 5)

        scroll_area.setWidget(container)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(scroll_area)
        main_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(main_layout)

        self.plugin_class_expanders: dict[str, Expander] = {}
        # self.refresh()

        # def refresh(self) -> None:
        app = neon_player.instance()

        # Clear all existing child widgets
        for i in reversed(range(self.container_layout.count())):
            layout_item = self.container_layout.itemAt(i)
            if layout_item:
                widget = layout_item.widget()
                widget.deleteLater()

        general_settings_form = PropertyForm(app.settings)
        expander = Expander(
            title="General Settings", content_widget=general_settings_form
        )
        self.container_layout.addWidget(expander)

        # Add a spacer to fill the remaining space
        self.spacer = QWidget()
        self.spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.container_layout.addWidget(self.spacer)

    def remove_plugin_settings(self, class_name: str) -> None:
        expander = self.plugin_class_expanders[class_name]
        self.container_layout.removeWidget(expander)
        expander.deleteLater()
        del self.plugin_class_expanders[class_name]

    def add_plugin_settings(self, instance: Plugin) -> None:
        cls = instance.__class__
        class_name = cls.__name__

        settings_form = PropertyForm(instance)
        label = cls.label if hasattr(cls, "label") else cls.__name__
        expander = Expander(title=label, content_widget=settings_form)

        self.container_layout.insertWidget(self.container_layout.count() - 1, expander)
        self.plugin_class_expanders[class_name] = expander
