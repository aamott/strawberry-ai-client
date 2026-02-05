"""Settings service - bridges SettingsManager to GUI V2."""

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from ....shared.settings import SettingsManager
    from ....shared.settings.schema import SettingField

logger = logging.getLogger(__name__)


class SettingsService(QObject):
    """Service that bridges SettingsManager to Qt signals.

    Provides:
    - Access to registered namespaces and their schemas
    - Getting/setting values with change notifications
    - Dynamic options for DYNAMIC_SELECT fields
    - Action execution for ACTION fields

    Signals:
        settings_changed: Emitted when a setting changes
                         (str: namespace, str: key, Any: value)
        save_completed: Emitted when settings are saved
        error_occurred: Emitted on errors (str: error_message)
    """

    settings_changed = Signal(str, str, object)  # namespace, key, value
    save_completed = Signal()
    error_occurred = Signal(str)

    def __init__(
        self,
        settings_manager: Optional["SettingsManager"] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._manager = settings_manager

        if self._manager:
            self._manager.on_change(self._on_settings_changed)

    def set_manager(self, manager: "SettingsManager") -> None:
        """Set the SettingsManager instance."""
        self._manager = manager
        self._manager.on_change(self._on_settings_changed)

    def _on_settings_changed(self, namespace: str, key: str, value: Any) -> None:
        """Handle settings change from SettingsManager."""
        self.settings_changed.emit(namespace, key, value)

    def get_namespaces(self) -> List[Dict[str, Any]]:
        """Get all registered namespaces with metadata.

        Returns:
            List of dicts with 'name', 'display_name', 'order', 'tab' keys.
        """
        if not self._manager:
            return []

        namespaces = []
        for ns in self._manager.get_namespaces():
            namespaces.append({
                "name": ns.name,
                "display_name": ns.display_name,
                "order": ns.order,
                "tab": ns.tab,
            })

        # Sort by order
        namespaces.sort(key=lambda x: x["order"])
        return namespaces

    def get_schema(self, namespace: str) -> List["SettingField"]:
        """Get the schema for a namespace.

        Args:
            namespace: Namespace name.

        Returns:
            List of SettingField objects.
        """
        if not self._manager:
            return []
        return self._manager.get_schema(namespace)

    def get_all(self, namespace: str) -> Dict[str, Any]:
        """Get all settings for a namespace.

        Args:
            namespace: Namespace name.

        Returns:
            Dict of key -> value.
        """
        if not self._manager:
            return {}
        return self._manager.get_all(namespace)

    def get(self, namespace: str, key: str, default: Any = None) -> Any:
        """Get a single setting value.

        Args:
            namespace: Namespace name.
            key: Setting key.
            default: Default value if not set.

        Returns:
            The setting value.
        """
        if not self._manager:
            return default
        return self._manager.get(namespace, key, default)

    def set(self, namespace: str, key: str, value: Any) -> Optional[str]:
        """Set a single setting value.

        Args:
            namespace: Namespace name.
            key: Setting key.
            value: New value.

        Returns:
            Error message if validation failed, None on success.
        """
        if not self._manager:
            return "SettingsManager not initialized"
        return self._manager.set(namespace, key, value)

    def update(self, namespace: str, values: Dict[str, Any]) -> Dict[str, str]:
        """Update multiple settings at once.

        Args:
            namespace: Namespace name.
            values: Dict of key -> value to update.

        Returns:
            Dict of key -> error message for any validation failures.
        """
        if not self._manager:
            return {"_error": "SettingsManager not initialized"}
        return self._manager.update(namespace, values)

    def save(self) -> None:
        """Persist all settings to storage."""
        if self._manager:
            self._manager.save()
            self.save_completed.emit()

    def get_options(self, provider: str) -> List[str]:
        """Get dynamic options for a DYNAMIC_SELECT field.

        Args:
            provider: Options provider name.

        Returns:
            List of option strings.
        """
        if not self._manager:
            return []
        return self._manager.get_options(provider) or []

    async def execute_action(self, namespace: str, action: str) -> Any:
        """Execute a settings action.

        Args:
            namespace: Namespace name.
            action: Action name.

        Returns:
            ActionResult from the handler.
        """
        if not self._manager:
            self.error_occurred.emit("SettingsManager not initialized")
            return None

        try:
            return await self._manager.execute_action(namespace, action)
        except Exception as e:
            self.error_occurred.emit(str(e))
            return None

    @property
    def manager(self) -> Optional["SettingsManager"]:
        """Get the SettingsManager instance."""
        return self._manager
