"""Widget that renders a single SettingField.

This widget creates the appropriate Qt widget for a SettingField
based on its type.
"""

from typing import Any, Callable, List, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from strawberry.shared.settings import FieldType, SettingField


class SchemaFieldWidget(QWidget):
    """Widget that renders a single SettingField.

    Signals:
        value_changed(str, object): Emitted when the value changes (key, value).
        action_triggered(str): Emitted when an action button is clicked (action).
    """

    value_changed = Signal(str, object)  # key, value
    action_triggered = Signal(str)  # action name

    def __init__(
        self,
        field: SettingField,
        value: Any = None,
        options_provider: Optional[Callable[[str], List[str]]] = None,
        parent: Optional[QWidget] = None,
    ):
        """Initialize the schema field widget.

        Args:
            field: The SettingField definition.
            value: Current value for the field.
            options_provider: Callback to get options for DYNAMIC_SELECT fields.
            parent: Parent widget.
        """
        super().__init__(parent)
        self._field = field
        self._value = value if value is not None else field.default
        self._options_provider = options_provider
        self._inner_widget: Optional[QWidget] = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the widget UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._inner_widget = self._create_widget()
        if self._inner_widget:
            layout.addWidget(self._inner_widget)

        # specific metadata help?
        if self._field.metadata and "help_text" in self._field.metadata:
            help_btn = QPushButton("?")
            help_btn.setFixedWidth(24)
            help_btn.setToolTip(self._field.metadata["help_text"])
            # Optional: styled to look less like a primary action
            help_btn.setStyleSheet("font-weight: bold; color: #888;")
            layout.addWidget(help_btn)

    def _create_widget(self) -> Optional[QWidget]:
        """Create the appropriate widget for the field type.

        Returns:
            The created widget or None.
        """
        field = self._field
        value = self._value

        if field.type == FieldType.TEXT:
            widget = QLineEdit()
            widget.setText(str(value) if value else "")
            if field.placeholder:
                widget.setPlaceholderText(field.placeholder)
            widget.textChanged.connect(self._emit_change)
            return widget

        elif field.type == FieldType.PASSWORD:
            widget = QLineEdit()
            widget.setEchoMode(QLineEdit.EchoMode.Password)
            widget.setText(str(value) if value else "")
            widget.setPlaceholderText(
                field.placeholder or ("••••••••" if value else "Enter value...")
            )
            widget.textChanged.connect(self._emit_change)
            return widget

        elif field.type == FieldType.NUMBER:
            if isinstance(field.default, float):
                widget = QDoubleSpinBox()
                widget.setDecimals(2)
                if field.min_value is not None:
                    widget.setMinimum(field.min_value)
                else:
                    widget.setMinimum(-999999)
                if field.max_value is not None:
                    widget.setMaximum(field.max_value)
                else:
                    widget.setMaximum(999999)
                widget.setValue(float(value) if value else 0.0)
                widget.valueChanged.connect(self._emit_change)
            else:
                widget = QSpinBox()
                if field.min_value is not None:
                    widget.setMinimum(int(field.min_value))
                else:
                    widget.setMinimum(-999999)
                if field.max_value is not None:
                    widget.setMaximum(int(field.max_value))
                else:
                    widget.setMaximum(999999)
                widget.setValue(int(value) if value else 0)
                widget.valueChanged.connect(self._emit_change)
            return widget

        elif field.type == FieldType.CHECKBOX:
            widget = QCheckBox()
            widget.setChecked(bool(value))
            widget.stateChanged.connect(lambda s: self._emit_change(bool(s)))
            return widget

        elif field.type == FieldType.SELECT:
            widget = QComboBox()
            if field.options:
                widget.addItems(field.options)
                if value in field.options:
                    widget.setCurrentText(str(value))
            widget.currentTextChanged.connect(self._emit_change)
            return widget

        elif field.type == FieldType.DYNAMIC_SELECT:
            widget = QComboBox()
            if self._options_provider and field.options_provider:
                try:
                    options = self._options_provider(field.options_provider)
                    widget.addItems(options)
                    if value and str(value) in options:
                        widget.setCurrentText(str(value))
                except Exception:
                    if value:
                        widget.addItem(str(value))
            widget.currentTextChanged.connect(self._emit_change)
            return widget

        elif field.type == FieldType.ACTION:
            widget = QPushButton(field.label)
            widget.clicked.connect(lambda: self._emit_action())
            return widget

        elif field.type == FieldType.MULTILINE:
            widget = QPlainTextEdit()
            widget.setPlainText(str(value) if value else "")
            widget.setMaximumHeight(100)
            if field.placeholder:
                widget.setPlaceholderText(field.placeholder)
            widget.textChanged.connect(
                lambda: self._emit_change(widget.toPlainText())
            )
            return widget

        elif field.type == FieldType.LIST or field.type == FieldType.PROVIDER_SELECT:
            # Render as comma-separated text for now
            # TODO: Future - reorderable list widget
            widget = QLineEdit()
            text = ""
            if isinstance(value, list):
                text = ", ".join(str(v) for v in value)
            elif value:
                text = str(value)

            widget.setText(text)
            if field.placeholder:
                widget.setPlaceholderText(field.placeholder)

            # For PROVIDER_SELECT/LIST, we convert text back to list on change
            # But _create_widget just connects the signal. serialization happens in get_value/emit
            def on_change(text):
                items = [x.strip() for x in text.split(",") if x.strip()]
                self._emit_change(items)

            widget.textChanged.connect(on_change)
            return widget

        return None

    def _emit_change(self, value: Any) -> None:
        """Emit value change signal.

        Args:
            value: The new value.
        """
        self._value = value
        self.value_changed.emit(self._field.key, value)

    def _emit_action(self) -> None:
        """Emit action trigger signal."""
        if self._field.action:
            self.action_triggered.emit(self._field.action)

    def get_value(self) -> Any:
        """Get the current widget value.

        Returns:
            The current value.
        """
        widget = self._inner_widget

        if isinstance(widget, QLineEdit):
            return widget.text()
        elif isinstance(widget, QCheckBox):
            return widget.isChecked()
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            return widget.value()
        elif isinstance(widget, QComboBox):
            return widget.currentText()
        elif isinstance(widget, QPlainTextEdit):
            return widget.toPlainText()
        elif isinstance(widget, QLineEdit) and (
            self._field.type == FieldType.LIST or self._field.type == FieldType.PROVIDER_SELECT
        ):
            # Parse comma-separated list
            text = widget.text()
            return [x.strip() for x in text.split(",") if x.strip()]

        return self._value

    def set_value(self, value: Any) -> None:
        """Set the widget value without triggering change signals.

        Args:
            value: The new value.
        """
        self._value = value
        widget = self._inner_widget

        if widget is None:
            return

        widget.blockSignals(True)

        if isinstance(widget, QLineEdit):
            widget.setText(str(value) if value else "")
        elif isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.setValue(value if value else 0)
        elif isinstance(widget, QComboBox):
            idx = widget.findText(str(value))
            if idx >= 0:
                widget.setCurrentIndex(idx)
        elif isinstance(widget, QPlainTextEdit):
            widget.setPlainText(str(value) if value else "")
        elif isinstance(widget, QLineEdit) and (
            self._field.type == FieldType.LIST or self._field.type == FieldType.PROVIDER_SELECT
        ):
            text = ""
            if isinstance(value, list):
                text = ", ".join(str(v) for v in value)
            elif value:
                text = str(value)
            widget.setText(text)

        widget.blockSignals(False)

    def refresh_dynamic_options(self) -> None:
        """Refresh options for a DYNAMIC_SELECT field."""
        if self._field.type != FieldType.DYNAMIC_SELECT:
            return

        widget = self._inner_widget
        if not isinstance(widget, QComboBox):
            return

        if self._options_provider and self._field.options_provider:
            try:
                current = widget.currentText()
                options = self._options_provider(self._field.options_provider)
                widget.blockSignals(True)
                widget.clear()
                widget.addItems(options)
                if current in options:
                    widget.setCurrentText(current)
                widget.blockSignals(False)
            except Exception:
                pass
