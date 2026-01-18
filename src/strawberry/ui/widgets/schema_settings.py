"""Schema-driven settings widget for auto-rendering from SettingField definitions.

This widget automatically creates form fields based on a list of SettingField
definitions, supporting all FieldType variants.
"""

from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...core.settings_schema import FieldType, SettingField


class SchemaSettingsWidget(QWidget):
    """Widget that auto-renders settings from a SettingField schema.
    
    Signals:
        value_changed(str, Any): Emitted when a field value changes (key, value)
        action_triggered(str): Emitted when an ACTION button is clicked
    """

    value_changed = Signal(str, object)  # key, value
    action_triggered = Signal(str)  # action name

    def __init__(
        self,
        schema: List[SettingField],
        values: Optional[Dict[str, Any]] = None,
        options_provider: Optional[Callable[[str], List[str]]] = None,
        parent: Optional[QWidget] = None,
    ):
        """Initialize the schema settings widget.
        
        Args:
            schema: List of SettingField definitions
            values: Current values for each field (by key)
            options_provider: Callback to get options for DYNAMIC_SELECT fields
            parent: Parent widget
        """
        super().__init__(parent)

        self._schema = schema
        self._values = values or {}
        self._options_provider = options_provider
        self._widgets: Dict[str, QWidget] = {}
        self._hidden_by_depends: Dict[str, QWidget] = {}

        self._setup_ui()

    def _setup_ui(self):
        """Build the form from the schema."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Group fields by group attribute
        groups: Dict[str, List[SettingField]] = {}
        for field in self._schema:
            if field.group not in groups:
                groups[field.group] = []
            groups[field.group].append(field)

        # Create a group box for each group
        for group_name, fields in groups.items():
            group_box = QGroupBox(group_name.replace("_", " ").title())
            group_layout = QFormLayout(group_box)

            for field in fields:
                widget = self._create_field_widget(field)
                if widget:
                    self._widgets[field.key] = widget

                    # Create label with description tooltip
                    label = QLabel(field.label + ":")
                    if field.description:
                        label.setToolTip(field.description)
                        widget.setToolTip(field.description)

                    group_layout.addRow(label, widget)

                    # Handle depends_on visibility
                    if field.depends_on:
                        self._hidden_by_depends[field.key] = widget
                        # Store the label too for hiding
                        widget.setProperty("_label", label)

            layout.addWidget(group_box)

        layout.addStretch()

        # Apply initial depends_on visibility
        self._update_visibility()

    def _create_field_widget(self, field: SettingField) -> Optional[QWidget]:
        """Create the appropriate widget for a field type."""
        value = self._values.get(field.key, field.default)

        if field.type == FieldType.TEXT:
            widget = QLineEdit()
            widget.setText(str(value) if value else "")
            widget.textChanged.connect(
                lambda v, k=field.key: self._on_value_changed(k, v)
            )
            return widget

        elif field.type == FieldType.PASSWORD:
            widget = QLineEdit()
            widget.setEchoMode(QLineEdit.EchoMode.Password)
            widget.setText(str(value) if value else "")
            widget.textChanged.connect(
                lambda v, k=field.key: self._on_value_changed(k, v)
            )
            return widget

        elif field.type == FieldType.NUMBER:
            # Use int or float based on default type
            if isinstance(field.default, float):
                widget = QDoubleSpinBox()
                widget.setRange(-999999, 999999)
                widget.setDecimals(2)
                widget.setValue(float(value) if value else 0.0)
                widget.valueChanged.connect(
                    lambda v, k=field.key: self._on_value_changed(k, v)
                )
            else:
                widget = QSpinBox()
                widget.setRange(-999999, 999999)
                widget.setValue(int(value) if value else 0)
                widget.valueChanged.connect(
                    lambda v, k=field.key: self._on_value_changed(k, v)
                )
            return widget

        elif field.type == FieldType.CHECKBOX:
            widget = QCheckBox()
            widget.setChecked(bool(value))
            widget.stateChanged.connect(
                lambda s, k=field.key: self._on_value_changed(k, bool(s))
            )
            return widget

        elif field.type == FieldType.SELECT:
            widget = QComboBox()
            if field.options:
                widget.addItems(field.options)
                if value and value in field.options:
                    widget.setCurrentText(str(value))
            widget.currentTextChanged.connect(
                lambda v, k=field.key: self._on_value_changed(k, v)
            )
            return widget

        elif field.type == FieldType.DYNAMIC_SELECT:
            widget = QComboBox()
            # Populate from options_provider
            if self._options_provider and field.options_provider:
                try:
                    options = self._options_provider(field.options_provider)
                    widget.addItems(options)
                    if value and str(value) in options:
                        widget.setCurrentText(str(value))
                except Exception:
                    widget.addItem(str(value) if value else "")
            widget.currentTextChanged.connect(
                lambda v, k=field.key: self._on_value_changed(k, v)
            )
            return widget

        elif field.type == FieldType.ACTION:
            widget = QPushButton(field.label)
            widget.clicked.connect(
                lambda checked=False, a=field.action: self.action_triggered.emit(a)
            )
            return widget

        return None

    def _on_value_changed(self, key: str, value: Any):
        """Handle value change and emit signal."""
        self._values[key] = value
        self.value_changed.emit(key, value)

        # Update visibility for depends_on fields
        self._update_visibility()

    def _update_visibility(self):
        """Update visibility based on depends_on relationships."""
        for key, widget in self._hidden_by_depends.items():
            field = next((f for f in self._schema if f.key == key), None)
            if field and field.depends_on:
                depends_value = self._values.get(field.depends_on)
                visible = bool(depends_value)
                widget.setVisible(visible)
                # Also hide the label if stored
                label = widget.property("_label")
                if label:
                    label.setVisible(visible)

    def get_values(self) -> Dict[str, Any]:
        """Get all current field values.
        
        Returns:
            Dictionary mapping keys to current values
        """
        return dict(self._values)

    def set_values(self, values: Dict[str, Any]):
        """Set multiple field values at once.
        
        Args:
            values: Dictionary mapping keys to new values
        """
        for key, value in values.items():
            self.set_value(key, value)

    def set_value(self, key: str, value: Any):
        """Set a single field value.
        
        Args:
            key: The field key
            value: The new value
        """
        self._values[key] = value
        widget = self._widgets.get(key)

        if not widget:
            return

        # Update widget without triggering signals
        if isinstance(widget, QLineEdit):
            widget.blockSignals(True)
            widget.setText(str(value) if value else "")
            widget.blockSignals(False)
        elif isinstance(widget, QCheckBox):
            widget.blockSignals(True)
            widget.setChecked(bool(value))
            widget.blockSignals(False)
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.blockSignals(True)
            widget.setValue(value if value else 0)
            widget.blockSignals(False)
        elif isinstance(widget, QComboBox):
            widget.blockSignals(True)
            if widget.findText(str(value)) >= 0:
                widget.setCurrentText(str(value))
            widget.blockSignals(False)

    def refresh_dynamic_options(self, key: str):
        """Refresh options for a DYNAMIC_SELECT field.
        
        Args:
            key: The field key to refresh
        """
        field = next((f for f in self._schema if f.key == key), None)
        if not field or field.type != FieldType.DYNAMIC_SELECT:
            return

        widget = self._widgets.get(key)
        if not isinstance(widget, QComboBox):
            return

        if self._options_provider and field.options_provider:
            try:
                current = widget.currentText()
                options = self._options_provider(field.options_provider)
                widget.blockSignals(True)
                widget.clear()
                widget.addItems(options)
                if current in options:
                    widget.setCurrentText(current)
                widget.blockSignals(False)
            except Exception:
                pass
