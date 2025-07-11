from PySide6.QtWidgets import (
    QWidget,
)
from qt_property_widgets.widgets import PropertyForm

from pupil_labs.neon_player import Plugin
from pupil_labs.neon_player.expander import Expander, ExpanderList


class SettingsPanel(ExpanderList):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.setMinimumSize(400, 100)

        self.plugin_class_expanders: dict[str, Expander] = {}

    def add_plugin_settings(self, instance: Plugin) -> None:
        cls = instance.__class__
        class_name = cls.__name__

        settings_form = PropertyForm(instance)
        label = cls.label if hasattr(cls, "label") else cls.__name__
        expander = self.add_expander(label, settings_form)
        self.plugin_class_expanders[class_name] = expander

    def remove_plugin_settings(self, class_name: str) -> None:
        expander = self.plugin_class_expanders[class_name]
        self.remove_expander(expander)
        del self.plugin_class_expanders[class_name]
