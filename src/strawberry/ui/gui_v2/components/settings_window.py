"""Settings window - decoupled settings dialog for GUI V2.

This is a standalone window that can be opened from the main interface.
It uses the existing Qt settings field widgets for consistency.
"""

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
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

logger = logging.getLogger(__name__)


class SettingsWindow(QDialog):
    """Decoupled settings window for GUI V2.

    Opens as a separate dialog window. Uses schema-driven rendering
    to display settings organized by tabs and namespaces.

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
        self.setWindowTitle("Settings")
        self.setMinimumSize(700, 500)
        self.resize(800, 600)

        # Use native styling (clear any inherited stylesheet)
        self.setStyleSheet("")

    def _build_ui(self) -> None:
        """Build the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # Tab widget for organizing settings
        self._tabs = QTabWidget()
        layout.addWidget(self._tabs, 1)

        # Build tabs from registered namespaces
        self._build_tabs()

        # Status label
        self._status_label = QLabel()
        self._status_label.setStyleSheet("color: gray; font-size: 12px;")
        layout.addWidget(self._status_label)

        # Button row
        button_layout = QHBoxLayout()

        self._apply_btn = QPushButton("Apply")
        self._apply_btn.clicked.connect(self._on_apply)
        self._apply_btn.setEnabled(False)

        self._discard_btn = QPushButton("Discard")
        self._discard_btn.clicked.connect(self._on_discard)
        self._discard_btn.setEnabled(False)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
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
        tabs: Dict[str, List["RegisteredNamespace"]] = {}
        for ns in namespaces:
            # Skip internal namespaces
            if ns.name.startswith("_"):
                continue
            tab_name = ns.tab
            if tab_name not in tabs:
                tabs[tab_name] = []
            tabs[tab_name].append(ns)

        # Sort tabs (General first, then alphabetical)
        tab_order = ["General", "Voice", "Skills"]
        sorted_tabs = sorted(
            tabs.keys(),
            key=lambda t: (tab_order.index(t) if t in tab_order else 100, t)
        )

        for tab_name in sorted_tabs:
            tab_widget = self._build_tab(tab_name, tabs[tab_name])
            self._tabs.addTab(tab_widget, tab_name)

    def _build_tab(
        self, tab_name: str, namespaces: List["RegisteredNamespace"]
    ) -> QWidget:
        """Build a single tab containing namespace sections."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        container = QWidget()
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
        """Build a section for a single namespace."""
        group = QGroupBox(ns.display_name)
        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        # Get current values
        values = self._settings.get_all(ns.name)

        # Build field widgets
        for field in ns.schema:
            widget = self._create_field_widget(ns.name, field, values)
            if widget:
                layout.addWidget(widget)

        return group

    def _create_field_widget(
        self, namespace: str, field: Any, values: Dict[str, Any]
    ) -> Optional[QWidget]:
        """Create a widget for a single field.

        Uses the existing Qt field widgets from ui/qt/settings/field_widgets.
        """
        try:
            from ...qt.settings.field_widgets import create_field_widget

            current_value = values.get(field.key, field.default)
            widget = create_field_widget(
                field=field,
                current_value=current_value,
                settings_manager=self._settings,
            )

            if widget:
                # Store reference
                key = f"{namespace}.{field.key}"
                self._field_widgets[key] = widget

                # Connect change signal
                widget.value_changed.connect(
                    lambda val, ns=namespace, k=field.key: self._on_field_changed(
                        ns, k, val
                    )
                )

            return widget

        except ImportError:
            logger.warning("Could not import field widgets from ui/qt")
            return self._create_simple_field_widget(namespace, field, values)

    def _create_simple_field_widget(
        self, namespace: str, field: Any, values: Dict[str, Any]
    ) -> QWidget:
        """Create a simple fallback widget for a field."""
        from ....shared.settings.schema import FieldType

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 4)

        # Label
        label = QLabel(field.label)
        label.setMinimumWidth(150)
        layout.addWidget(label)

        current_value = values.get(field.key, field.default)

        # Simple input based on type
        if field.type == FieldType.CHECKBOX:
            from PySide6.QtWidgets import QCheckBox

            checkbox = QCheckBox()
            checkbox.setChecked(bool(current_value))
            checkbox.stateChanged.connect(
                lambda state, ns=namespace, k=field.key: self._on_field_changed(
                    ns, k, state == Qt.CheckState.Checked.value
                )
            )
            layout.addWidget(checkbox)
            layout.addStretch()

        elif field.type == FieldType.SELECT and field.options:
            from PySide6.QtWidgets import QComboBox

            combo = QComboBox()
            combo.addItems(field.options)
            if current_value in field.options:
                combo.setCurrentText(str(current_value))
            combo.currentTextChanged.connect(
                lambda text, ns=namespace, k=field.key: self._on_field_changed(
                    ns, k, text
                )
            )
            layout.addWidget(combo, 1)

        elif field.type == FieldType.NUMBER:
            from PySide6.QtWidgets import QSpinBox

            spinbox = QSpinBox()
            spinbox.setRange(
                int(field.min_value or 0),
                int(field.max_value or 99999)
            )
            spinbox.setValue(int(current_value or 0))
            spinbox.valueChanged.connect(
                lambda val, ns=namespace, k=field.key: self._on_field_changed(
                    ns, k, val
                )
            )
            layout.addWidget(spinbox, 1)

        else:
            # Default to text input
            from PySide6.QtWidgets import QLineEdit

            line_edit = QLineEdit()
            line_edit.setText(str(current_value or ""))
            if field.type == FieldType.PASSWORD:
                line_edit.setEchoMode(QLineEdit.EchoMode.Password)
            line_edit.textChanged.connect(
                lambda text, ns=namespace, k=field.key: self._on_field_changed(
                    ns, k, text
                )
            )
            layout.addWidget(line_edit, 1)

        # Description tooltip
        if field.description:
            container.setToolTip(field.description)

        return container

    def _on_field_changed(self, namespace: str, key: str, value: Any) -> None:
        """Handle field value change."""
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

    def _on_apply(self) -> None:
        """Apply pending changes without closing."""
        if self._apply_changes():
            self._status_label.setText("Changes applied")

    def _on_discard(self) -> None:
        """Discard pending changes and reload values."""
        self._pending_changes.clear()
        self._reload_values()
        self._update_buttons()
        self._status_label.setText("Changes discarded")

    def _on_save(self) -> None:
        """Save changes and close dialog."""
        if self._apply_changes():
            self.settings_saved.emit()
            self.accept()

    def _apply_changes(self) -> bool:
        """Apply all pending changes.

        Returns:
            True if all changes applied successfully.
        """
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
                "Some settings could not be saved:\n\n" + "\n".join(errors)
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
        """Handle window close - prompt if unsaved changes."""
        if any(self._pending_changes.values()):
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes. Discard them?",
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel
            )
            if reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return

        super().closeEvent(event)
