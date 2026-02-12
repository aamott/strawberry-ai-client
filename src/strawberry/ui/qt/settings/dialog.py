"""Main settings dialog with tabs.

Provides a schema-driven settings interface organized by namespace tabs.
"""

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from strawberry.shared.settings import (
    FieldType,
    SettingField,
    SettingsManager,
    SettingsViewModel,
)

from .field_widgets import BaseFieldWidget, create_field_widget


class SettingsDialog(QDialog):
    """Main settings dialog with tab-based organization.

    Settings are grouped into tabs based on namespace.tab attribute.
    Changes are buffered until Apply/Save is clicked.

    Example:
        dialog = SettingsDialog(settings_manager, parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            print("Settings saved")
    """

    def __init__(
        self,
        settings_manager: SettingsManager,
        parent: Optional[QWidget] = None,
    ):
        """Initialize settings dialog.

        Args:
            settings_manager: The SettingsManager instance.
            parent: Parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(700, 500)

        # Clear inherited stylesheet to use native Qt styling
        # The main window applies a global custom theme that breaks
        # settings UI elements (pink buttons, invisible checkmarks, etc.)
        self.setStyleSheet("")

        self._settings = settings_manager
        self.vm = SettingsViewModel(settings_manager)

        # Pending changes: namespace -> {key: value}
        self.pending_changes: Dict[str, Dict[str, Any]] = {}

        # Field widgets by namespace.key for validation
        self._field_widgets: Dict[str, BaseFieldWidget] = {}

        self._build_ui()

    def _build_ui(self) -> None:
        """Build the dialog UI."""
        layout = QVBoxLayout(self)

        # Tab widget
        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        # Build tabs from namespaces grouped by tab attribute
        self._build_tabs()

        # Status bar
        self._status_label = QLabel()
        self._status_label.setStyleSheet("color: gray;")
        layout.addWidget(self._status_label)

        # Buttons
        button_layout = QHBoxLayout()

        self._apply_btn = QPushButton("Apply")
        self._apply_btn.clicked.connect(self._on_apply)
        self._apply_btn.setEnabled(False)

        self._discard_btn = QPushButton("Discard")
        self._discard_btn.clicked.connect(self._on_discard)
        self._discard_btn.setEnabled(False)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._on_save)
        button_box.rejected.connect(self.reject)

        button_layout.addWidget(self._apply_btn)
        button_layout.addWidget(self._discard_btn)
        button_layout.addStretch()
        button_layout.addWidget(button_box)

        layout.addLayout(button_layout)

    def _build_tabs(self) -> None:
        """Build tabs from registered namespaces."""
        namespaces = self._settings.get_namespaces()

        # Group namespaces by tab
        tabs: Dict[str, List] = {}
        for ns in namespaces:
            tab_name = ns.tab
            if tab_name not in tabs:
                tabs[tab_name] = []
            tabs[tab_name].append(ns)

        # Sort tabs (General first, then alphabetical)
        tab_order = ["General", "Voice", "Skills"]
        sorted_tabs = sorted(
            tabs.keys(), key=lambda t: (tab_order.index(t) if t in tab_order else 100, t)
        )

        for tab_name in sorted_tabs:
            tab_widget = self._build_tab(tab_name, tabs[tab_name])
            self._tabs.addTab(tab_widget, tab_name)

    def _build_tab(self, tab_name: str, namespaces: List) -> QWidget:
        """Build a single tab containing namespace sections.

        Args:
            tab_name: The tab name.
            namespaces: List of RegisteredNamespace objects.

        Returns:
            The tab widget.
        """
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(16)

        # Sort namespaces by order
        for ns in sorted(namespaces, key=lambda x: x.order):
            section = self._build_section(ns)
            layout.addWidget(section)

        layout.addStretch()
        scroll.setWidget(container)
        return scroll

    def _build_section(self, namespace) -> QWidget:
        """Build a section for a namespace.

        Args:
            namespace: RegisteredNamespace object.

        Returns:
            Section widget.
        """
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(8, 8, 8, 8)

        # Section header
        header = QLabel(f"<b>{namespace.display_name}</b>")
        header.setStyleSheet("font-size: 14px; margin-bottom: 8px;")
        layout.addWidget(header)

        # Get current values
        values = self._settings.get_all(namespace.name)

        # Group fields
        groups: Dict[str, List[SettingField]] = {}
        for field in namespace.schema:
            group = field.group
            if group not in groups:
                groups[group] = []
            groups[group].append(field)

        # Build field widgets by group
        for group_name, fields in groups.items():
            if group_name != "general":
                group_label = QLabel(f"<i>{group_name}</i>")
                group_label.setStyleSheet("color: gray; margin-top: 8px;")
                layout.addWidget(group_label)

            for field in fields:
                current_value = values.get(field.key, field.default)
                widget = self._create_field_widget(namespace.name, field, current_value)
                layout.addWidget(widget)

        return section

    def _create_field_widget(
        self,
        namespace: str,
        field: SettingField,
        current_value: Any,
    ) -> BaseFieldWidget:
        """Create a field widget and connect signals.

        Args:
            namespace: The namespace.
            field: Field definition.
            current_value: Current value.

        Returns:
            The field widget.
        """
        # Get available providers for PROVIDER_SELECT
        kwargs = {}
        if field.type == FieldType.PROVIDER_SELECT:
            if field.provider_type:
                providers = self._get_available_providers(
                    field.provider_type, field.options_provider
                )
                kwargs["available_providers"] = providers
            elif field.options:
                # Static options list (e.g. LLM fallback order)
                kwargs["available_providers"] = list(field.options)

        widget = create_field_widget(field, current_value, self)

        # Set available providers if applicable
        if hasattr(widget, "set_available_providers") and "available_providers" in kwargs:
            widget.set_available_providers(kwargs["available_providers"])

        # Set health status for provider widgets
        if field.type == FieldType.PROVIDER_SELECT and field.provider_type:
            health_provider = f"{field.provider_type}_backend_health"
            health_status = self._settings.get_options(health_provider)
            if health_status and hasattr(widget, "set_provider_health"):
                widget.set_provider_health(health_status)

        # Connect value change
        widget.value_changed.connect(
            lambda v, ns=namespace, k=field.key: self._on_field_changed(ns, k, v)
        )

        # Store widget reference
        key = f"{namespace}.{field.key}"
        self._field_widgets[key] = widget

        return widget

    def _get_available_providers(
        self, provider_type: str, options_provider: str | None = None
    ) -> List[str]:
        """Get available providers from options provider or registered namespaces.

        Args:
            provider_type: Type like "stt", "tts", "vad", "wakeword".
            options_provider: Name of registered options provider (preferred).

        Returns:
            List of available provider names.
        """
        # Try options provider first (populated by VoiceCore with discovered modules)
        if options_provider:
            providers = self._settings.get_options(options_provider)
            if providers:
                return providers

        # Fallback to registered namespaces
        prefix = f"voice.{provider_type}."
        providers = []
        for ns in self._settings.get_namespaces():
            if ns.name.startswith(prefix):
                providers.append(ns.name.split(".")[-1])
        return providers

    def _on_field_changed(self, namespace: str, key: str, value: Any) -> None:
        """Handle field value change.

        Args:
            namespace: The namespace.
            key: The field key.
            value: New value.
        """
        if namespace not in self.pending_changes:
            self.pending_changes[namespace] = {}
        self.pending_changes[namespace][key] = value

        self._update_status()

    def _update_status(self) -> None:
        """Update status bar and button states."""
        count = sum(len(v) for v in self.pending_changes.values())
        has_changes = count > 0

        self._apply_btn.setEnabled(has_changes)
        self._discard_btn.setEnabled(has_changes)

        if has_changes:
            self._status_label.setText(f"{count} pending change(s)")
        else:
            self._status_label.setText("")

    def _validate_all(self) -> List[str]:
        """Validate all pending changes.

        Returns:
            List of error messages.
        """
        errors = []

        for namespace, changes in self.pending_changes.items():
            for key, value in changes.items():
                field = self._settings.get_field(namespace, key)
                if field:
                    error = field.validate(value)
                    if error:
                        errors.append(f"{namespace}.{key}: {error}")

                        # Apply red glow to widget
                        widget_key = f"{namespace}.{key}"
                        if widget_key in self._field_widgets:
                            self._field_widgets[widget_key].set_invalid(error)
                    else:
                        widget_key = f"{namespace}.{key}"
                        if widget_key in self._field_widgets:
                            self._field_widgets[widget_key].set_valid()

        return errors

    def _on_apply(self) -> None:
        """Apply pending changes without closing dialog."""
        errors = self._validate_all()
        if errors:
            QMessageBox.warning(
                self,
                "Validation Error",
                "Please fix the following errors:\n\n" + "\n".join(errors),
            )
            return

        # Apply using batch mode
        self._settings.begin_batch()
        try:
            for namespace, changes in self.pending_changes.items():
                for key, value in changes.items():
                    self.vm.set_value(namespace, key, value)
            self._settings.end_batch(emit=True)
            self.pending_changes.clear()
            self._update_status()
            self._status_label.setText("Changes applied")
        except Exception as e:
            self._settings.end_batch(emit=False)
            QMessageBox.critical(self, "Error", f"Failed to apply changes: {e}")

    def _on_discard(self) -> None:
        """Discard pending changes."""
        # Reset widgets to original values
        for namespace, changes in self.pending_changes.items():
            for key in changes:
                original = self._settings.get(namespace, key)
                widget_key = f"{namespace}.{key}"
                if widget_key in self._field_widgets:
                    self._field_widgets[widget_key].set_value(original)
                    self._field_widgets[widget_key].set_valid()

        self.pending_changes.clear()
        self._update_status()

    def _on_save(self) -> None:
        """Apply changes and save to disk."""
        if self.pending_changes:
            errors = self._validate_all()
            if errors:
                QMessageBox.warning(
                    self,
                    "Validation Error",
                    "Please fix the following errors:\n\n" + "\n".join(errors),
                )
                return

            # Apply changes
            self._settings.begin_batch()
            try:
                for namespace, changes in self.pending_changes.items():
                    for key, value in changes.items():
                        self.vm.set_value(namespace, key, value)
                self._settings.end_batch(emit=True)
            except Exception as e:
                self._settings.end_batch(emit=False)
                QMessageBox.critical(self, "Error", f"Failed to apply changes: {e}")
                return

        # Save to disk
        try:
            self._settings.save()
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save: {e}")
