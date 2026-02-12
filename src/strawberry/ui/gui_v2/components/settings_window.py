"""Settings window for GUI V2.

A themed settings dialog that integrates with the gui_v2 dark theme.
Uses its own field widgets (gui_v2/settings/) — no dependency on the
old ui/qt/settings/ widgets.
"""

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from ....shared.settings import SettingsManager
    from ....shared.settings.manager import RegisteredNamespace
    from ....shared.settings.schema import SettingField

logger = logging.getLogger(__name__)

# ── Theme-aware stylesheet for the settings window ──────────────────────
_WINDOW_STYLE = """
    QDialog#SettingsWindow {
        background-color: #1a1a2e;
        color: #ffffff;
    }

    /* Tab bar */
    QTabWidget::pane {
        border: 1px solid #2a2a4a;
        border-radius: 8px;
        background-color: #16213e;
        top: -1px;
    }
    QTabBar::tab {
        background-color: #1a1a2e;
        color: #a0a0a0;
        border: 1px solid #2a2a4a;
        border-bottom: none;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        padding: 8px 20px;
        margin-right: 2px;
        font-size: 13px;
    }
    QTabBar::tab:selected {
        background-color: #16213e;
        color: #ffffff;
        border-bottom: 2px solid #e94560;
    }
    QTabBar::tab:hover:!selected {
        background-color: #2a2a4a;
        color: #ffffff;
    }

    /* Scroll area */
    QScrollArea {
        background-color: transparent;
        border: none;
    }

    /* Section frames */
    QFrame#NamespaceSection {
        background-color: #1e1e3f;
        border: 1px solid #2a2a4a;
        border-radius: 8px;
        padding: 4px;
    }

    /* Group labels */
    QLabel#GroupLabel {
        color: #666666;
        font-size: 11px;
        font-style: italic;
    }

    /* Section header */
    QLabel#SectionHeader {
        color: #ffffff;
        font-size: 14px;
        font-weight: bold;
    }

    /* Status label */
    QLabel#StatusLabel {
        color: #666666;
        font-size: 12px;
    }

    /* Buttons */
    QPushButton#ApplyBtn, QPushButton#DiscardBtn {
        background-color: #2a2a4a;
        color: #ffffff;
        border: 1px solid #3a3a5a;
        border-radius: 6px;
        padding: 8px 16px;
        font-size: 13px;
    }
    QPushButton#ApplyBtn:hover, QPushButton#DiscardBtn:hover {
        background-color: #3a3a5a;
    }
    QPushButton#ApplyBtn:disabled, QPushButton#DiscardBtn:disabled {
        color: #666666;
        background-color: #1a1a2e;
        border-color: #2a2a4a;
    }
    QPushButton#SaveBtn {
        background-color: #e94560;
        color: #ffffff;
        border: none;
        border-radius: 6px;
        padding: 8px 24px;
        font-size: 13px;
        font-weight: bold;
    }
    QPushButton#SaveBtn:hover {
        background-color: #d63851;
    }
    QPushButton#SaveBtn:pressed {
        background-color: #c02d44;
    }
    QPushButton#CancelBtn {
        background-color: transparent;
        color: #a0a0a0;
        border: 1px solid #2a2a4a;
        border-radius: 6px;
        padding: 8px 16px;
        font-size: 13px;
    }
    QPushButton#CancelBtn:hover {
        color: #ffffff;
        border-color: #3a3a5a;
    }

    /* Scrollbar */
    QScrollBar:vertical {
        width: 8px;
        background: transparent;
    }
    QScrollBar::handle:vertical {
        background-color: #2a2a4a;
        border-radius: 4px;
        min-height: 30px;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0;
    }
"""


class SettingsWindow(QDialog):
    """Themed settings window for GUI V2.

    Opens as a separate dialog window. Uses schema-driven rendering
    to display settings organized by tabs and namespaces, styled to
    match the gui_v2 dark theme.

    Signals:
        settings_saved: Emitted when settings are saved
        settings_changed: Emitted when any setting changes
                         (str: namespace, str: key, Any: value)
    """

    settings_saved = Signal()
    settings_changed = Signal(str, str, object)

    def __init__(
        self,
        settings_manager: "SettingsManager",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._settings = settings_manager
        self._pending_changes: Dict[str, Dict[str, Any]] = {}
        self._field_widgets: Dict[str, Any] = {}  # namespace.key -> widget

        self._setup_window()
        self._build_ui()

    def _setup_window(self) -> None:
        """Configure the window."""
        self.setObjectName("SettingsWindow")
        self.setWindowTitle("Settings")
        self.setMinimumSize(700, 500)
        self.resize(800, 600)
        self.setStyleSheet(_WINDOW_STYLE)

    def _build_ui(self) -> None:
        """Build the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Title
        title = QLabel("⚙  Settings")
        title.setStyleSheet(
            "color: #ffffff; font-size: 18px; font-weight: bold; margin-bottom: 4px;"
        )
        layout.addWidget(title)

        # Status label (create early so it exists before field widgets)
        self._status_label = QLabel()
        self._status_label.setObjectName("StatusLabel")

        # Create buttons early (field widgets may trigger _update_buttons during creation)
        self._apply_btn = QPushButton("Apply")
        self._apply_btn.setObjectName("ApplyBtn")
        self._apply_btn.clicked.connect(self._on_apply)
        self._apply_btn.setEnabled(False)

        self._discard_btn = QPushButton("Discard")
        self._discard_btn.setObjectName("DiscardBtn")
        self._discard_btn.clicked.connect(self._on_discard)
        self._discard_btn.setEnabled(False)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setObjectName("CancelBtn")
        self._cancel_btn.clicked.connect(self.reject)

        self._save_btn = QPushButton("Save")
        self._save_btn.setObjectName("SaveBtn")
        self._save_btn.clicked.connect(self._on_save)

        # Tab widget for organizing settings
        self._tabs = QTabWidget()
        layout.addWidget(self._tabs, 1)

        # Build tabs from registered namespaces
        self._build_tabs()

        # Add status label
        layout.addWidget(self._status_label)

        # Button row
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)
        button_layout.addWidget(self._apply_btn)
        button_layout.addWidget(self._discard_btn)
        button_layout.addStretch()
        button_layout.addWidget(self._cancel_btn)
        button_layout.addWidget(self._save_btn)

        layout.addLayout(button_layout)

    def _build_tabs(self) -> None:
        """Build tabs from registered namespaces."""
        namespaces = self._settings.get_namespaces()

        # Group namespaces by tab
        tabs: Dict[str, List["RegisteredNamespace"]] = {}
        for ns in namespaces:
            # Skip internal namespaces
            if ns.name.startswith("_"):
                continue
            tab_name = ns.tab
            if tab_name not in tabs:
                tabs[tab_name] = []
            tabs[tab_name].append(ns)

        # Sort tabs by the minimum namespace order within each tab, then alphabetically
        sorted_tabs = sorted(
            tabs.keys(), key=lambda t: (min(ns.order for ns in tabs[t]), t)
        )

        for tab_name in sorted_tabs:
            tab_widget = self._build_tab(tab_name, tabs[tab_name])
            self._tabs.addTab(tab_widget, tab_name)

    def _build_tab(
        self, tab_name: str, namespaces: List["RegisteredNamespace"]
    ) -> QWidget:
        """Build a single tab containing namespace sections.

        Args:
            tab_name: The tab name.
            namespaces: List of RegisteredNamespace objects.

        Returns:
            The tab widget.
        """
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        container.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(16)

        # Sort namespaces by order
        sorted_ns = sorted(namespaces, key=lambda ns: ns.order)

        for ns in sorted_ns:
            section = self._build_namespace_section(ns)
            layout.addWidget(section)

        layout.addStretch()
        scroll.setWidget(container)
        return scroll

    def _build_namespace_section(self, ns: "RegisteredNamespace") -> QWidget:
        """Build a section for a single namespace.

        Args:
            ns: RegisteredNamespace object.

        Returns:
            Section widget.
        """
        section = QFrame()
        section.setObjectName("NamespaceSection")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Section header
        header = QLabel(ns.display_name)
        header.setObjectName("SectionHeader")
        layout.addWidget(header)

        # Get current values
        values = self._settings.get_all(ns.name)

        # Group fields by group attribute
        groups: Dict[str, List["SettingField"]] = {}
        for field in ns.schema:
            group = field.group
            if group not in groups:
                groups[group] = []
            groups[group].append(field)

        # Build field widgets by group
        for group_name, fields in groups.items():
            if group_name != "general":
                group_label = QLabel(group_name)
                group_label.setObjectName("GroupLabel")
                layout.addWidget(group_label)

            for field in fields:
                widget = self._create_field_widget(ns.name, field, values)
                if widget:
                    layout.addWidget(widget)

        return section

    def _create_field_widget(
        self,
        namespace: str,
        field: "SettingField",
        values: Dict[str, Any],
    ) -> Optional[QWidget]:
        """Create a themed field widget.

        Uses gui_v2/settings/ field widgets (self-contained, themed).

        Args:
            namespace: The namespace name.
            field: The SettingField definition.
            values: Current values for the namespace.

        Returns:
            The field widget, or None on error.
        """
        from ..settings.field_factory import create_field_widget

        try:
            current_value = values.get(field.key, field.default)
            widget = create_field_widget(
                field=field,
                current_value=current_value,
                parent=self,
            )

            # Store reference
            key = f"{namespace}.{field.key}"
            self._field_widgets[key] = widget

            # Connect change signal
            widget.value_changed.connect(
                lambda val, ns=namespace, k=field.key: self._on_field_changed(ns, k, val)
            )

            # Handle PROVIDER_SELECT: populate available providers
            from ....shared.settings.schema import FieldType

            if field.type == FieldType.PROVIDER_SELECT:
                if field.provider_type:
                    providers = self._get_available_providers(
                        field.provider_type, field.options_provider
                    )
                elif field.options:
                    # Static options list (e.g. LLM fallback order)
                    providers = list(field.options)
                else:
                    providers = []

                if providers and hasattr(widget, "set_available_providers"):
                    widget.set_available_providers(providers)

                # Set health status if available
                if field.provider_type:
                    health_provider = (
                        f"{field.provider_type}_backend_health"
                    )
                    health_status = self._settings.get_options(
                        health_provider,
                    )
                    if health_status and hasattr(
                        widget, "set_provider_health",
                    ):
                        widget.set_provider_health(health_status)

            # Handle DYNAMIC_SELECT: populate options from provider
            if field.type == FieldType.DYNAMIC_SELECT and field.options_provider:
                options = self._settings.get_options(field.options_provider)
                if options and hasattr(widget, "set_options"):
                    widget.set_options(options)

            return widget

        except Exception:
            logger.exception(f"Failed to create widget for {namespace}.{field.key}")
            return None

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
        # Try options provider first
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
        if namespace not in self._pending_changes:
            self._pending_changes[namespace] = {}

        self._pending_changes[namespace][key] = value
        self._update_buttons()
        self.settings_changed.emit(namespace, key, value)

    def _update_buttons(self) -> None:
        """Update button states based on pending changes."""
        has_changes = any(self._pending_changes.values())
        self._apply_btn.setEnabled(has_changes)
        self._discard_btn.setEnabled(has_changes)

        if has_changes:
            count = sum(len(v) for v in self._pending_changes.values())
            self._status_label.setText(f"{count} unsaved change(s)")
        else:
            self._status_label.setText("")

    def _validate_all(self) -> List[str]:
        """Validate all pending changes.

        Returns:
            List of error messages.
        """
        errors = []
        for namespace, changes in self._pending_changes.items():
            for key, value in changes.items():
                field = self._settings.get_field(namespace, key)
                if field:
                    error = field.validate(value)
                    if error:
                        errors.append(f"{namespace}.{key}: {error}")
                        # Mark widget as invalid
                        widget_key = f"{namespace}.{key}"
                        if widget_key in self._field_widgets:
                            self._field_widgets[widget_key].set_invalid(error)
                    else:
                        widget_key = f"{namespace}.{key}"
                        if widget_key in self._field_widgets:
                            self._field_widgets[widget_key].set_valid()
        return errors

    def _on_apply(self) -> None:
        """Apply pending changes without closing."""
        errors = self._validate_all()
        if errors:
            QMessageBox.warning(
                self,
                "Validation Errors",
                "Please fix the following errors:\n\n" + "\n".join(errors),
            )
            return

        if self._apply_changes():
            self._status_label.setText("Changes applied")

    def _on_discard(self) -> None:
        """Discard pending changes and reload values."""
        self._pending_changes.clear()
        self._reload_values()
        self._update_buttons()
        self._status_label.setText("Changes discarded")

    def _on_save(self) -> None:
        """Validate, save changes, and close dialog."""
        if self._pending_changes:
            errors = self._validate_all()
            if errors:
                QMessageBox.warning(
                    self,
                    "Validation Errors",
                    "Please fix the following errors:\n\n" + "\n".join(errors),
                )
                return

        if self._apply_changes():
            self.settings_saved.emit()
            self.accept()

    def _apply_changes(self) -> bool:
        """Apply all pending changes.

        Returns:
            True if all changes applied successfully.
        """
        if not self._pending_changes:
            return True

        errors = []
        for namespace, changes in self._pending_changes.items():
            result = self._settings.update(namespace, changes)
            if result:
                for key, error in result.items():
                    errors.append(f"{namespace}.{key}: {error}")

        if errors:
            QMessageBox.warning(
                self,
                "Validation Errors",
                "Some settings could not be saved:\n\n" + "\n".join(errors),
            )
            return False

        # Save to storage
        self._settings.save()
        self._pending_changes.clear()
        self._update_buttons()
        return True

    def _reload_values(self) -> None:
        """Reload all field values from settings."""
        for key, widget in self._field_widgets.items():
            namespace, field_key = key.split(".", 1)
            value = self._settings.get(namespace, field_key)
            if hasattr(widget, "set_value"):
                widget.set_value(value)

    def closeEvent(self, event) -> None:
        """Handle window close — prompt if unsaved changes."""
        if any(self._pending_changes.values()):
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes. Discard them?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return

        super().closeEvent(event)
