"""Shared field editing logic for settings UIs.

Centralizes value formatting, pending-change management, and list
manipulation so that CLI, test CLI, and Qt frontends only need to
provide I/O adapters (prompt, print, dialog).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .manager import SettingsManager
from .schema import FieldType, SettingField
from .view_model import SettingsViewModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Value formatting (shared across all UIs)
# ---------------------------------------------------------------------------


def format_field_value(field: SettingField, value: Any) -> str:
    """Render a field value as a human-readable string.

    This is the single source of truth for how settings values are
    displayed across all UIs (CLI, test CLI, Qt).

    Args:
        field: The field schema definition.
        value: The current value.

    Returns:
        Formatted display string.
    """
    if value is None:
        return "(not set)"

    match field.type:
        case FieldType.PASSWORD:
            return "••••••••" if value else "(not set)"
        case FieldType.CHECKBOX:
            return "[x]" if value else "[ ]"
        case FieldType.NUMBER | FieldType.SLIDER:
            return f"{value}{_format_range(field)}"
        case FieldType.LIST | FieldType.PROVIDER_SELECT:
            if isinstance(value, list):
                return " → ".join(str(v) for v in value)
            return str(value)
        case FieldType.SELECT | FieldType.DYNAMIC_SELECT:
            opts = field.options or []
            if opts:
                return f"{value} (options: {', '.join(opts[:3])}...)"
            return str(value)
        case FieldType.COLOR:
            return value if value else "#000000"
        case FieldType.ACTION:
            return f"[{field.label}]"
        case _:
            return str(value) if value else "(empty)"


def _format_range(field: SettingField) -> str:
    """Format the min/max range suffix for numeric fields."""
    if field.min_value is None and field.max_value is None:
        return ""
    min_v = field.min_value if field.min_value is not None else ""
    max_v = field.max_value if field.max_value is not None else ""
    return f" [{min_v}..{max_v}]"


# ---------------------------------------------------------------------------
# Pending-change controller
# ---------------------------------------------------------------------------


class PendingChangeController:
    """Manages buffered settings changes with validate/apply/discard/reset.

    Used by UIs that want deferred saving (e.g., Apply/OK pattern).
    UIs that save immediately can skip this and call
    ``SettingsViewModel.set_value`` directly.

    Example:
        ctrl = PendingChangeController(settings_manager)
        ctrl.set_value("voice_core", "stt.order", ["whisper", "leopard"])
        errors = ctrl.apply()  # persists to disk
    """

    def __init__(self, settings_manager: SettingsManager):
        self._settings = settings_manager
        self._vm = SettingsViewModel(settings_manager)
        self._pending: Dict[str, Dict[str, Any]] = {}

    @property
    def view_model(self) -> SettingsViewModel:
        """Access the underlying view model."""
        return self._vm

    # -- read -----------------------------------------------------------------

    def get_value(self, namespace: str, key: str) -> Any:
        """Get a value, preferring any pending change over the stored value.

        Args:
            namespace: Settings namespace.
            key: Field key.

        Returns:
            Pending value if buffered, otherwise the stored value.
        """
        pending = self._pending.get(namespace, {}).get(key)
        if pending is not None:
            return pending
        return self._vm.get_value(namespace, key)

    # -- write ----------------------------------------------------------------

    def set_value(self, namespace: str, key: str, value: Any) -> Optional[str]:
        """Buffer a value change after validation.

        Args:
            namespace: Settings namespace.
            key: Field key.
            value: New value.

        Returns:
            Validation error message, or None if valid.
        """
        field = self._settings.get_field(namespace, key)
        if field:
            error = field.validate(value)
            if error:
                return error

        if namespace not in self._pending:
            self._pending[namespace] = {}
        self._pending[namespace][key] = value
        return None

    def reset_field(self, namespace: str, key: str) -> Optional[str]:
        """Buffer a reset-to-default for a field.

        Args:
            namespace: Settings namespace.
            key: Field key.

        Returns:
            Error message if field not found, else None.
        """
        field = self._settings.get_field(namespace, key)
        if not field:
            return f"Field '{key}' not found in '{namespace}'"

        current = self._vm.get_value(namespace, key)
        if current == field.default:
            return None  # already at default

        if namespace not in self._pending:
            self._pending[namespace] = {}
        self._pending[namespace][key] = field.default
        return None

    # -- lifecycle ------------------------------------------------------------

    def apply(self) -> List[str]:
        """Apply all pending changes and save to disk.

        Returns:
            List of error messages (empty on full success).
        """
        errors: List[str] = []
        self._settings.begin_batch()

        try:
            for namespace, changes in self._pending.items():
                for key, value in changes.items():
                    try:
                        self._vm.set_value(namespace, key, value)
                    except Exception as e:
                        errors.append(f"{namespace}.{key}: {e}")

            if not errors:
                self._settings.end_batch(emit=True)
                self._settings.save()
                self._pending.clear()
            else:
                self._settings.end_batch(emit=False)
        except Exception as e:
            self._settings.end_batch(emit=False)
            errors.append(str(e))

        return errors

    def discard(self) -> int:
        """Discard all pending changes.

        Returns:
            Number of discarded changes.
        """
        count = sum(len(v) for v in self._pending.values())
        self._pending.clear()
        return count

    def has_pending(self) -> bool:
        """Check if there are any buffered changes."""
        return any(len(v) > 0 for v in self._pending.values())

    def pending_count(self) -> int:
        """Get the total number of buffered changes."""
        return sum(len(v) for v in self._pending.values())

    def get_pending_for(self, namespace: str, key: str) -> Any:
        """Get the pending value for a specific field, or None."""
        return self._pending.get(namespace, {}).get(key)


# ---------------------------------------------------------------------------
# List manipulation helpers
# ---------------------------------------------------------------------------


def list_add(items: List[str], value: str) -> List[str]:
    """Append an item to a list.

    Args:
        items: Current list (mutated in place).
        value: Value to add.

    Returns:
        The mutated list.
    """
    items.append(value)
    return items


def list_remove(items: List[str], index: int) -> Optional[str]:
    """Remove an item by 0-based index.

    Args:
        items: Current list (mutated in place).
        index: 0-based index.

    Returns:
        The removed item, or None if index was invalid.
    """
    if 0 <= index < len(items):
        return items.pop(index)
    return None


def list_move_up(items: List[str], index: int) -> bool:
    """Move an item one position up (toward index 0).

    Args:
        items: Current list (mutated in place).
        index: 0-based index of item to move.

    Returns:
        True if the move was performed.
    """
    if 0 < index < len(items):
        items[index - 1], items[index] = items[index], items[index - 1]
        return True
    return False


def list_move_down(items: List[str], index: int) -> bool:
    """Move an item one position down (toward end).

    Args:
        items: Current list (mutated in place).
        index: 0-based index of item to move.

    Returns:
        True if the move was performed.
    """
    if 0 <= index < len(items) - 1:
        items[index], items[index + 1] = items[index + 1], items[index]
        return True
    return False


def get_available_options(
    settings: SettingsManager,
    field: SettingField,
    current_items: List[str],
) -> List[str]:
    """Get options not already in the current list.

    Works for LIST, PROVIDER_SELECT, and any field with ``options``
    or ``options_provider``.

    Args:
        settings: The SettingsManager (for dynamic option providers).
        field: Field definition.
        current_items: Already-selected items.

    Returns:
        List of options not yet in ``current_items``.
    """
    if field.options:
        return [opt for opt in field.options if opt not in current_items]

    if field.options_provider:
        all_opts = settings.get_options(field.options_provider)
        return [opt for opt in all_opts if opt not in current_items]

    # PROVIDER_SELECT — discover from registered namespaces
    if field.type == FieldType.PROVIDER_SELECT and field.provider_type:
        prefix = f"voice.{field.provider_type}."
        available = []
        for ns in settings.get_namespaces():
            if ns.name.startswith(prefix):
                backend = ns.name.split(".")[-1]
                if backend not in current_items:
                    available.append(backend)
        return available

    return []
