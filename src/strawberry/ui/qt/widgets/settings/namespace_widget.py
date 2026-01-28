"""Widget for displaying settings for a single namespace.

This widget renders all settings for a namespace, organized by groups,
and includes provider selection widgets for voice backends.
"""

from typing import Any, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from strawberry.shared.settings import SettingsViewModel

from .provider_widget import ProviderSettingsWidget
from .schema_field_widget import SchemaFieldWidget


class NamespaceSettingsWidget(QWidget):
    """Widget that renders all settings for a namespace.

    Signals:
        value_changed(str, str, object): Emitted when a field changes
            (namespace, key, value).
        action_triggered(str, str): Emitted when an action button is clicked
            (namespace, action).
    """

    value_changed = Signal(str, str, object)  # namespace, key, value
    action_triggered = Signal(str, str)  # namespace, action

    def __init__(
        self,
        view_model: SettingsViewModel,
        namespace: str,
        parent: Optional[QWidget] = None,
    ):
        """Initialize the namespace settings widget.

        Args:
            view_model: The SettingsViewModel to read settings.
            namespace: The namespace identifier.
            parent: Parent widget.
        """
        super().__init__(parent)
        self._view_model = view_model
        self._namespace = namespace
        self._field_widgets: dict[str, SchemaFieldWidget] = {}
        self._provider_widgets: list[ProviderSettingsWidget] = []

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the widget UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        section = self._view_model.get_section(self._namespace)
        if not section:
            layout.addWidget(QLabel("No settings available"))
            return

        # Render groups
        for group_name, fields in section.groups.items():
            # Filter out fields handled by provider widgets
            filtered_fields = [
                f for f in fields
                if not f.key.endswith(".order") and not f.key.endswith(".backend")
            ]

            if not filtered_fields:
                continue

            group_box = QGroupBox(self._format_group_name(group_name))
            group_layout = QFormLayout(group_box)

            for field in filtered_fields:
                if self._namespace == "mcp" and field.key == "servers":
                    from .mcp_servers_widget import MCPServersWidget

                    widget = MCPServersWidget(
                        key=field.key,
                        value=section.values.get(field.key),
                    )
                    widget.value_changed.connect(
                        lambda k, v, ns=self._namespace: self._on_field_change(ns, k, v)
                    )
                else:
                    widget = SchemaFieldWidget(
                        field=field,
                        value=section.values.get(field.key),
                        options_provider=self._view_model.get_options,
                    )
                    widget.value_changed.connect(
                        lambda k, v, ns=self._namespace: self._on_field_change(ns, k, v)
                    )
                    widget.action_triggered.connect(
                        lambda a, ns=self._namespace: self.action_triggered.emit(ns, a)
                    )
                    self._field_widgets[field.key] = widget

                label = QLabel(field.label + ":")
                if field.description:
                    label.setToolTip(field.description)

                # Show lock icon for secrets
                if field.secret:
                    label.setText("🔒 " + label.text())

                group_layout.addRow(label, widget)

            layout.addWidget(group_box)

        # Render provider sections (STT, TTS, etc.)
        provider_sections = self._view_model.get_provider_sections(self._namespace)
        for ps in provider_sections:
            widget = ProviderSettingsWidget(
                view_model=self._view_model,
                provider_section=ps,
            )
            widget.value_changed.connect(self._on_provider_value_change)
            widget.action_triggered.connect(
                lambda ns, a: self.action_triggered.emit(ns, a)
            )
            self._provider_widgets.append(widget)
            layout.addWidget(widget)

        layout.addStretch()

    def _format_group_name(self, name: str) -> str:
        """Format group name for display.

        Args:
            name: The raw group name.

        Returns:
            Human-readable group name.
        """
        return name.replace("_", " ").title()

    def _on_field_change(self, namespace: str, key: str, value: Any) -> None:
        """Handle field value changes.

        Args:
            namespace: The namespace.
            key: The field key.
            value: The new value.
        """
        # Update via view model
        self._view_model.set_value(namespace, key, value)
        self.value_changed.emit(namespace, key, value)

    def _on_provider_value_change(
        self, namespace: str, key: str, value: Any
    ) -> None:
        """Handle provider value changes.

        Args:
            namespace: The namespace (may be provider sub-namespace).
            key: The field key.
            value: The new value.
        """
        self.value_changed.emit(namespace, key, value)

    def refresh(self) -> None:
        """Refresh all field values from the view model."""
        section = self._view_model.get_section(self._namespace)
        if not section:
            return

        for key, widget in self._field_widgets.items():
            value = section.values.get(key)
            widget.set_value(value)

        for pw in self._provider_widgets:
            pw.refresh()
