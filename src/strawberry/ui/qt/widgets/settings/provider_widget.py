"""Widget for selecting a provider and showing its settings.

This widget handles provider selection (e.g., STT/TTS backends)
and displays the selected provider's specific settings inline.
"""

from typing import Any, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from strawberry.shared.settings import ProviderSection, SettingsViewModel

from .schema_field_widget import SchemaFieldWidget


class ProviderSettingsWidget(QWidget):
    """Widget for selecting a provider and showing its settings.

    Shows:
    - Dropdown to select the primary provider
    - Inline settings for the selected provider

    Signals:
        value_changed(str, str, object): Emitted when a value changes
            (namespace, key, value).
        action_triggered(str, str): Emitted when an action is triggered
            (namespace, action).
        provider_changed(str): Emitted when the provider changes.
    """

    value_changed = Signal(str, str, object)  # namespace, key, value
    action_triggered = Signal(str, str)  # namespace, action
    provider_changed = Signal(str)  # new provider name

    def __init__(
        self,
        view_model: SettingsViewModel,
        provider_section: ProviderSection,
        parent: Optional[QWidget] = None,
    ):
        """Initialize the provider settings widget.

        Args:
            view_model: The SettingsViewModel to read settings.
            provider_section: The provider section configuration.
            parent: Parent widget.
        """
        super().__init__(parent)
        self._view_model = view_model
        self._section = provider_section
        self._field_widgets: dict[str, SchemaFieldWidget] = {}

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the widget UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Main group box
        display_name = self._section.provider_display_name or "Provider"
        group_box = QGroupBox(f"{display_name} Provider")
        group_layout = QVBoxLayout(group_box)

        # Provider selection row
        select_layout = QHBoxLayout()
        select_layout.addWidget(QLabel("Provider:"))

        self._provider_combo = QComboBox()
        self._provider_combo.addItems(self._section.available_providers)
        if self._section.selected_provider:
            idx = self._provider_combo.findText(self._section.selected_provider)
            if idx >= 0:
                self._provider_combo.setCurrentIndex(idx)
        self._provider_combo.currentTextChanged.connect(self._on_provider_changed)
        select_layout.addWidget(self._provider_combo)
        select_layout.addStretch()

        group_layout.addLayout(select_layout)

        # Provider-specific settings (indented frame)
        self._settings_frame = QFrame()
        self._settings_frame.setFrameStyle(QFrame.Shape.StyledPanel)
        self._settings_layout = QVBoxLayout(self._settings_frame)
        self._settings_layout.setContentsMargins(20, 10, 10, 10)

        self._populate_provider_settings()

        group_layout.addWidget(self._settings_frame)
        layout.addWidget(group_box)

    def _populate_provider_settings(self) -> None:
        """Populate the settings frame with current provider's settings."""
        # Clear existing
        self._field_widgets.clear()
        while self._settings_layout.count():
            item = self._settings_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Get provider settings
        provider_type = self._get_provider_type()
        provider_name = self._provider_combo.currentText()

        if not provider_name:
            self._settings_layout.addWidget(QLabel("Select a provider"))
            return

        section = self._view_model.get_provider_settings(provider_type, provider_name)

        if not section or not section.groups:
            self._settings_layout.addWidget(QLabel("No additional settings"))
            return

        # Render provider settings
        for group_name, fields in section.groups.items():
            form = QFormLayout()

            for field in fields:
                widget = SchemaFieldWidget(
                    field=field,
                    value=section.values.get(field.key),
                    options_provider=self._view_model.get_options,
                )
                widget.value_changed.connect(
                    lambda k, v, ns=section.namespace: self._on_provider_field_change(
                        ns, k, v
                    )
                )
                widget.action_triggered.connect(
                    lambda a, ns=section.namespace: self.action_triggered.emit(ns, a)
                )

                self._field_widgets[f"{section.namespace}:{field.key}"] = widget

                label = QLabel(field.label + ":")
                if field.description:
                    label.setToolTip(field.description)

                # Show lock icon for secrets
                if field.secret:
                    label.setText("🔒 " + label.text())

                form.addRow(label, widget)

            self._settings_layout.addLayout(form)

    def _get_provider_type(self) -> str:
        """Get the provider type from the provider key.

        Returns:
            Provider type string (e.g., "stt", "tts").
        """
        key = self._section.provider_key
        # Extract type from key like "stt.order" or "tts.backend"
        parts = key.split(".")
        if parts:
            return parts[0]
        return ""

    def _on_provider_changed(self, provider_name: str) -> None:
        """Handle provider selection change.

        Args:
            provider_name: The newly selected provider.
        """
        # Update the fallback order - put selected provider first
        self._view_model.set_primary_provider(
            self._section.parent_namespace,
            self._section.provider_key,
            provider_name,
        )

        # Update section
        self._section.selected_provider = provider_name
        provider_type = self._get_provider_type()
        self._section.provider_settings_namespace = (
            f"voice.{provider_type}.{provider_name}"
        )

        # Emit change for the order field
        new_order = self._view_model.get_value(
            self._section.parent_namespace, self._section.provider_key
        )
        self.value_changed.emit(
            self._section.parent_namespace, self._section.provider_key, new_order
        )

        # Refresh provider settings
        self._populate_provider_settings()
        self.provider_changed.emit(provider_name)

    def _on_provider_field_change(
        self, namespace: str, key: str, value: Any
    ) -> None:
        """Handle provider setting changes.

        Args:
            namespace: The provider namespace.
            key: The field key.
            value: The new value.
        """
        self._view_model.set_value(namespace, key, value)
        self.value_changed.emit(namespace, key, value)

    def refresh(self) -> None:
        """Refresh provider selection and settings from the view model."""
        # Update provider selection
        order = self._view_model.get_provider_order(
            self._section.parent_namespace, self._section.provider_key
        )
        if order:
            first_provider = order[0]
            idx = self._provider_combo.findText(first_provider)
            if idx >= 0:
                self._provider_combo.blockSignals(True)
                self._provider_combo.setCurrentIndex(idx)
                self._provider_combo.blockSignals(False)
                self._section.selected_provider = first_provider

        # Refresh provider settings
        self._populate_provider_settings()
