"""Main settings dialog with tabs for each namespace.

This dialog uses the SettingsViewModel to display settings organized
by namespace, with tabs for each registered namespace.
"""

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QMessageBox,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from strawberry.shared.settings import SettingsManager, SettingsViewModel

from .namespace_widget import NamespaceSettingsWidget


class SettingsDialog(QDialog):
    """Main settings dialog with tabs for each namespace.

    Example usage:
        settings_manager = SettingsManager(config_dir=Path("config"))
        dialog = SettingsDialog(settings_manager, parent=main_window)
        if dialog.exec() == QDialog.Accepted:
            print("Settings saved")
    """

    def __init__(
        self,
        settings_manager: SettingsManager,
        parent: Optional[QWidget] = None,
    ):
        """Initialize the settings dialog.

        Args:
            settings_manager: The SettingsManager to read/write settings.
            parent: Parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(700, 550)
        self.setMinimumSize(500, 400)

        self._settings = settings_manager
        self._view_model = SettingsViewModel(settings_manager)
        self._namespace_widgets: dict[str, NamespaceSettingsWidget] = {}
        self._pending_changes: dict[str, dict[str, object]] = {}

        self._setup_ui()
        self._view_model.on_refresh(self._on_external_refresh)

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # Tab widget for sections
        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        # Populate tabs
        self._populate_tabs()

        # Dialog buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        apply_btn = buttons.button(QDialogButtonBox.StandardButton.Apply)
        if apply_btn:
            apply_btn.clicked.connect(self._apply_changes)
        layout.addWidget(buttons)

    def _populate_tabs(self) -> None:
        """Create a tab for each settings section."""
        self._tabs.clear()
        self._namespace_widgets.clear()

        for section in self._view_model.get_sections():
            # Create scrollable widget for this section
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)

            widget = NamespaceSettingsWidget(
                view_model=self._view_model,
                namespace=section.namespace,
            )
            widget.value_changed.connect(self._on_value_changed)
            widget.action_triggered.connect(self._on_action_triggered)

            scroll.setWidget(widget)
            self._namespace_widgets[section.namespace] = widget

            self._tabs.addTab(scroll, section.display_name)

    def _on_value_changed(self, namespace: str, key: str, value: object) -> None:
        """Handle value changes from namespace widgets.

        Args:
            namespace: The namespace that changed.
            key: The setting key that changed.
            value: The new value.
        """
        # Track pending changes for Apply
        if namespace not in self._pending_changes:
            self._pending_changes[namespace] = {}
        self._pending_changes[namespace][key] = value

    def _on_action_triggered(self, namespace: str, action: str) -> None:
        """Handle action button clicks.

        Args:
            namespace: The namespace for the action.
            action: The action name.
        """
        import asyncio

        # Execute action asynchronously
        async def execute():
            result = await self._settings.execute_action(namespace, action)
            if result.type == "open_browser":
                import webbrowser
                if result.url:
                    webbrowser.open(result.url)
                if result.message:
                    QMessageBox.information(self, "Action", result.message)
            elif result.type == "error":
                QMessageBox.warning(self, "Error", result.message)
            elif result.type == "success":
                QMessageBox.information(self, "Success", result.message)

        # Run in event loop
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(execute())
            else:
                loop.run_until_complete(execute())
        except RuntimeError:
            # No event loop running, create one
            asyncio.run(execute())

    def _apply_changes(self) -> None:
        """Apply pending changes to the settings manager."""
        errors = []

        for namespace, values in self._pending_changes.items():
            result = self._settings.update(namespace, values)
            if result:
                for key, error in result.items():
                    errors.append(f"{namespace}.{key}: {error}")

        if errors:
            QMessageBox.warning(
                self,
                "Validation Errors",
                "Some settings could not be saved:\n\n" + "\n".join(errors),
            )
        else:
            self._pending_changes.clear()

    def _on_accept(self) -> None:
        """Handle dialog acceptance."""
        self._apply_changes()
        if not self._pending_changes:  # No errors remaining
            self.accept()

    def _on_external_refresh(self) -> None:
        """Refresh the UI when settings change externally."""
        # Refresh all namespace widgets
        for widget in self._namespace_widgets.values():
            widget.refresh()

    def showEvent(self, event) -> None:
        """Handle dialog show event."""
        super().showEvent(event)
        # Clear pending changes when dialog is shown
        self._pending_changes.clear()
