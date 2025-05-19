import typing as T

from PySide6.QtCore import (
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QSizePolicy,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qt_property_widgets.widgets import PropertyForm

from pupil_labs import neon_player
from pupil_labs.neon_player import Plugin
from pupil_labs.neon_player.expander import Expander


class PluginExpander(Expander):
    toggled = Signal(bool)

    def __init__(self, parent: T.Optional[QWidget] = None, title: str = "") -> None:
        super().__init__(parent=parent, title=title)

        self.toggle_button = QCheckBox("")
        self.toggle_button.setChecked(False)
        self.toggle_button.clicked.connect(self.on_toggle_button_clicked)

        self.grid_layout.addWidget(
            self.toggle_button, 0, 3, 1, 1, Qt.AlignmentFlag.AlignRight
        )

    def on_toggle_button_clicked(self) -> None:
        self.toggled.emit(self.toggle_button.isChecked())
        self.expander_button.setChecked(self.toggle_button.isChecked())


class SettingsPanel(QWidget):
    # @TODO make this scrollable
    def __init__(self, parent: T.Optional[QWidget] = None) -> None:
        super().__init__(parent=parent)

        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setMinimumSize(400, 100)

        container = QWidget()
        self.container_layout = QVBoxLayout(container)
        self.container_layout.setSpacing(0)

        scroll_area.setWidget(container)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(scroll_area)
        main_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(main_layout)

        self.plugin_class_expanders: dict[str, Expander] = {}
        self.refresh()

    def refresh(self) -> None:
        app = neon_player.instance()

        # Clear all existing child widgets
        for i in reversed(range(self.container_layout.count())):
            layout_item = self.container_layout.itemAt(i)
            if layout_item:
                widget = layout_item.widget()
                widget.deleteLater()

        expander = PluginExpander(title="General Settings")
        general_settings_form = PropertyForm(app.settings)
        expander.set_content_widget(general_settings_form)
        expander.toggle_button.setChecked(True)
        expander.toggle_button.setDisabled(True)
        self.container_layout.addWidget(expander)

        # Add new plugin widgets
        for plugin_class in Plugin.known_classes:
            if hasattr(plugin_class, "label"):
                label = plugin_class.label
            else:
                label = plugin_class.__name__

            expander = PluginExpander(title=label)
            expander.toggled.connect(
                lambda enabled, kls=plugin_class: app.toggle_plugin(kls, enabled)
            )
            self.container_layout.addWidget(expander)
            self.plugin_class_expanders[plugin_class.__name__] = expander

        # Add a spacer to fill the remaining space
        self.spacer = QWidget()
        self.spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.container_layout.addWidget(self.spacer)

    def set_plugin_instance(
        self, class_name: str, instance: T.Optional[Plugin]
    ) -> None:
        if instance is None:
            form = None

        else:
            expander = self.plugin_class_expanders[class_name]
            if hasattr(expander, "toggle_button"):
                expander.toggle_button.setChecked(True)

            form = PropertyForm(instance)
            if not form.has_widgets:
                form = None

        self.plugin_class_expanders[class_name].set_content_widget(form)
