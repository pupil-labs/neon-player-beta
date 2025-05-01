import typing as T

from PySide6.QtCore import (
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qt_property_widgets.widgets import PropertyForm

from pupil_labs import neon_player
from pupil_labs.neon_player import Plugin


class Expander(QWidget):
    toggled = Signal(bool)

    def __init__(self, parent: T.Optional[QWidget] = None, title: str = "") -> None:
        # Adapted from https://stackoverflow.com/a/56275050
        super().__init__(parent=parent)

        self.content_widget: T.Optional[QWidget] = None
        self.header_line = QFrame()
        self.expander_button = QToolButton()

        self.expander_button.setStyleSheet(
            "QToolButton { border: none; font-weight: bold; font-size: 12pt; }"
        )
        self.expander_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.expander_button.setText(str(title))
        self.expander_button.setCheckable(False)
        self.expander_button.setChecked(False)
        self.expander_button.setArrowType(Qt.ArrowType.LeftArrow)

        self.header_line.setFrameShape(QFrame.Shape.HLine)
        self.header_line.setFrameShadow(QFrame.Shadow.Sunken)
        self.header_line.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum
        )

        layout = QGridLayout()
        self.setLayout(layout)
        layout.setVerticalSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.expander_button, 0, 0, 1, 1, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.header_line, 0, 2, 1, 1)

        self.expander_button.toggled.connect(lambda _: self.on_expand_toggled())

        self.toggle_button = QCheckBox("")
        self.toggle_button.setChecked(False)
        self.toggle_button.clicked.connect(self.on_toggle_button_clicked)
        layout.addWidget(self.toggle_button, 0, 3, 1, 1, Qt.AlignmentFlag.AlignRight)

    def on_toggle_button_clicked(self) -> None:
        self.toggled.emit(self.toggle_button.isChecked())
        self.expander_button.setChecked(self.toggle_button.isChecked())

    def on_expand_toggled(self) -> None:
        checked = self.expander_button.isChecked()

        if checked:
            self.expander_button.setArrowType(Qt.ArrowType.DownArrow)
            if self.content_widget is not None:
                self.content_widget.show()
        else:
            self.expander_button.setArrowType(Qt.ArrowType.RightArrow)
            if self.content_widget is not None:
                self.content_widget.hide()

    def set_content_widget(self, content_widget: T.Union[QWidget, None]) -> None:
        layout = self.layout()

        if content_widget is None:
            if self.content_widget is not None:
                if layout:
                    layout.removeWidget(self.content_widget)

                self.content_widget.deleteLater()

            self.expander_button.setCheckable(False)
            self.expander_button.setArrowType(Qt.ArrowType.LeftArrow)
            self.content_widget = None

            return

        widget: QWidget = content_widget

        widget.setContentsMargins(20, 0, 0, 20)
        self.content_widget = widget

        self.expander_button.setCheckable(True)
        self.expander_button.setArrowType(Qt.ArrowType.RightArrow)
        if layout:
            layout.addWidget(self.content_widget, 1, 0, 1, 3)  # type: ignore

        self.content_widget.hide()


class SettingsPanel(QWidget):
    # @TODO make this scrollable
    def __init__(self, parent: T.Optional[QWidget] = None) -> None:
        super().__init__(parent=parent)

        self.setLayout(QVBoxLayout(self))
        self.plugin_class_expanders: dict[type, Expander] = {}
        self.refresh()
        self.setMinimumSize(350, 100)

    def refresh(self) -> None:
        app = neon_player.instance()

        # Clear all existing child widgets
        layout = self.layout()
        if layout:
            for i in reversed(range(layout.count())):
                layout_item = layout.itemAt(i)
                if layout_item:
                    widget = layout_item.widget()
                    widget.deleteLater()

        expander = Expander(title="General Settings")
        general_settings_form = PropertyForm(app.settings)
        expander.set_content_widget(general_settings_form)
        expander.toggle_button.setChecked(True)
        expander.toggle_button.setDisabled(True)
        if layout:
            layout.addWidget(expander)

        # Add new plugin widgets
        for plugin_class in Plugin.known_classes:
            if hasattr(plugin_class, "label"):
                label = plugin_class.label
            else:
                label = plugin_class.__name__

            expander = Expander(title=label)
            expander.toggled.connect(
                lambda enabled, kls=plugin_class: app.toggle_plugin(kls, enabled)
            )
            if layout:
                layout.addWidget(expander)
            self.plugin_class_expanders[plugin_class] = expander

        # Add a spacer to fill the remaining space
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        if layout:
            layout.addWidget(spacer)

    def set_plugin_instance(self, kls: type, instance: T.Optional[Plugin]) -> None:
        if instance is None:
            form = None

        else:
            self.plugin_class_expanders[kls].toggle_button.setChecked(True)
            form = PropertyForm(instance)
            if not form.has_widgets:
                form = None

        self.plugin_class_expanders[kls].set_content_widget(form)
