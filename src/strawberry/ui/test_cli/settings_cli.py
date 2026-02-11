"""CLI settings editor for testing and scripting.

This module provides a command-line interface for viewing and editing settings,
designed to work alongside test_cli for rapid iteration before Qt UI implementation.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from strawberry.shared.settings import (
    FieldType,
    SettingField,
    SettingsManager,
    SettingsViewModel,
)


@dataclass
class PendingChange:
    """A buffered change waiting for Apply."""

    namespace: str
    key: str
    old_value: Any
    new_value: Any


class SettingsCLI:
    """CLI settings editor using SettingsViewModel.

    Buffers changes until Apply is called, matching the Qt UI behavior.

    Example:
        cli = SettingsCLI(settings_manager)
        cli.list_namespaces()
        cli.show_namespace("voice_core")
        cli.set_value("voice_core", "stt.order", ["whisper", "leopard"])
        cli.apply_changes()
    """

    def __init__(self, settings_manager: SettingsManager):
        """Initialize CLI settings editor.

        Args:
            settings_manager: The SettingsManager instance.
        """
        self.vm = SettingsViewModel(settings_manager)
        self._settings = settings_manager
        self.pending_changes: Dict[str, Dict[str, Any]] = {}

    def list_namespaces(self) -> None:
        """Print all registered namespaces grouped by tab."""
        namespaces = self._settings.get_namespaces()

        # Group by tab
        tabs: Dict[str, List] = {}
        for ns in namespaces:
            tab = ns.tab
            if tab not in tabs:
                tabs[tab] = []
            tabs[tab].append(ns)

        for tab_name, ns_list in sorted(tabs.items()):
            print(f"\n── {tab_name} ──")
            for ns in sorted(ns_list, key=lambda x: x.order):
                field_count = len(ns.schema)
                print(f"  {ns.name}: {ns.display_name} ({field_count} fields)")

    def show_namespace(self, namespace: str) -> None:
        """Print all fields and values in a namespace.

        Args:
            namespace: The namespace to display.
        """
        section = self.vm.get_section(namespace)
        if not section:
            print(f"Error: Namespace '{namespace}' not found")
            return

        ns_info = self._settings.get_namespace(namespace)
        tab = ns_info.tab if ns_info else "General"

        print(f"\n═══ {section.display_name} ({namespace}) ═══")
        print(f"Tab: {tab}")

        for group_name, fields in section.groups.items():
            print(f"\n── {group_name} ──")
            for field in fields:
                value = section.values.get(field.key, field.default)
                # Check for pending change
                pending = self.pending_changes.get(namespace, {}).get(field.key)
                self._print_field(field, value, pending)

    def _print_field(
        self, field: SettingField, value: Any, pending: Any = None
    ) -> None:
        """Print a single field with its value.

        Args:
            field: The field definition.
            value: Current value.
            pending: Pending change value (if any).
        """
        display = self._render_field_value(field, value)

        # Show pending indicator
        if pending is not None:
            pending_display = self._render_field_value(field, pending)
            print(f"  {field.label}: {display} → {pending_display} [pending]")
        else:
            print(f"  {field.label}: {display}")

        # Show description on separate line if present
        if field.description:
            print(f"    └─ {field.description}")

    @staticmethod
    def _format_range(field: SettingField) -> str:
        """Format the min/max range suffix for numeric fields."""
        if field.min_value is None and field.max_value is None:
            return ""
        min_v = field.min_value if field.min_value is not None else ""
        max_v = field.max_value if field.max_value is not None else ""
        return f" [{min_v}..{max_v}]"

    def _render_field_value(self, field: SettingField, value: Any) -> str:
        """Render a field value for display.

        Args:
            field: The field definition.
            value: The value to render.

        Returns:
            Formatted string representation.
        """
        if value is None:
            return "(not set)"

        match field.type:
            case FieldType.PASSWORD:
                return "••••••••" if value else "(not set)"
            case FieldType.CHECKBOX:
                return "[x]" if value else "[ ]"
            case FieldType.NUMBER | FieldType.SLIDER:
                return f"{value}{self._format_range(field)}"
            case FieldType.LIST | FieldType.PROVIDER_SELECT:
                return " → ".join(str(v) for v in value) if isinstance(value, list) else str(value)
            case FieldType.SELECT | FieldType.DYNAMIC_SELECT:
                opts = field.options or []
                return f"{value} (options: {', '.join(opts[:3])}...)" if opts else str(value)
            case FieldType.COLOR:
                return value if value else "#000000"
            case FieldType.ACTION:
                return f"[{field.label}]"
            case _:
                return str(value) if value else "(empty)"

    def get_value(self, namespace: str, key: str) -> Any:
        """Get current value (including pending changes).

        Args:
            namespace: The namespace.
            key: The field key.

        Returns:
            Current or pending value.
        """
        # Check pending first
        pending = self.pending_changes.get(namespace, {}).get(key)
        if pending is not None:
            return pending

        return self.vm.get_value(namespace, key)

    def set_value(self, namespace: str, key: str, value: Any) -> Optional[str]:
        """Buffer a value change (doesn't apply until apply_changes).

        Args:
            namespace: The namespace.
            key: The field key.
            value: The new value.

        Returns:
            Validation error message or None if valid.
        """
        # Validate
        field = self._settings.get_field(namespace, key)
        if field:
            error = field.validate(value)
            if error:
                return error

        # Buffer the change
        if namespace not in self.pending_changes:
            self.pending_changes[namespace] = {}
        self.pending_changes[namespace][key] = value

        return None

    def apply_changes(self) -> List[str]:
        """Apply all pending changes.

        Returns:
            List of error messages (empty if all succeeded).
        """
        errors = []

        # Use batch mode to emit all changes at once
        self._settings.begin_batch()

        try:
            for namespace, changes in self.pending_changes.items():
                for key, value in changes.items():
                    try:
                        self.vm.set_value(namespace, key, value)
                    except Exception as e:
                        errors.append(f"{namespace}.{key}: {e}")

            if not errors:
                self._settings.end_batch(emit=True)
                self._settings.save()
                self.pending_changes.clear()
                print("✓ Changes applied and saved")
            else:
                self._settings.end_batch(emit=False)
                print("✗ Some changes failed:")
                for err in errors:
                    print(f"  - {err}")

        except Exception as e:
            self._settings.end_batch(emit=False)
            errors.append(str(e))

        return errors

    def discard_changes(self) -> None:
        """Discard all pending changes."""
        count = sum(len(v) for v in self.pending_changes.values())
        self.pending_changes.clear()
        print(f"Discarded {count} pending change(s)")

    def reset_field(self, namespace: str, key: str) -> None:
        """Reset a field to its default value.

        Args:
            namespace: The namespace.
            key: The field key.
        """
        field = self._settings.get_field(namespace, key)
        if not field:
            print(f"Error: Field '{key}' not found in '{namespace}'")
            return

        current = self.vm.get_value(namespace, key)
        if current == field.default:
            print(f"{field.label} is already at default value")
            return

        # Buffer the reset as a pending change
        if namespace not in self.pending_changes:
            self.pending_changes[namespace] = {}
        self.pending_changes[namespace][key] = field.default
        print(f"{field.label}: {current} → {field.default} [pending reset]")

    def has_pending_changes(self) -> bool:
        """Check if there are pending changes."""
        return any(len(v) > 0 for v in self.pending_changes.values())

    def get_pending_count(self) -> int:
        """Get the number of pending changes."""
        return sum(len(v) for v in self.pending_changes.values())

    def _list_cmd_add(self, items: list[str], field: SettingField) -> None:
        """Handle the 'add' command in the list editor."""
        available = self._get_available_options(field, items)
        if available:
            print("Available options:")
            for i, opt in enumerate(available, 1):
                print(f"  {i}. {opt}")
            choice = input("Select number or enter custom: ").strip()
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(available):
                    items.append(available[idx])
                else:
                    print("Invalid selection")
                    return
            except ValueError:
                if choice and (field.allow_custom or not field.options):
                    items.append(choice)
                else:
                    print("Custom values not allowed")
                    return
        else:
            new_item = input("Enter new item: ").strip()
            if new_item:
                items.append(new_item)
        self._print_list_items(items)

    @staticmethod
    def _list_cmd_move_up(items: list[str], cmd: str) -> None:
        """Handle the 'u N' (move up) command."""
        try:
            idx = int(cmd[2:]) - 1
            if 0 < idx < len(items):
                items[idx - 1], items[idx] = items[idx], items[idx - 1]
            else:
                print("Cannot move up")
        except (ValueError, IndexError):
            print("Invalid index")

    @staticmethod
    def _list_cmd_move_down(items: list[str], cmd: str) -> None:
        """Handle the 'd N' (move down) command."""
        try:
            idx = int(cmd[2:]) - 1
            if 0 <= idx < len(items) - 1:
                items[idx], items[idx + 1] = items[idx + 1], items[idx]
            else:
                print("Cannot move down")
        except (ValueError, IndexError):
            print("Invalid index")

    @staticmethod
    def _list_cmd_remove(items: list[str], cmd: str) -> None:
        """Handle the 'r N' (remove) command."""
        try:
            idx = int(cmd[2:]) - 1
            if 0 <= idx < len(items):
                print(f"Removed: {items.pop(idx)}")
            else:
                print("Invalid index")
        except (ValueError, IndexError):
            print("Invalid index")

    def _list_cmd_view_detail(self, items: list[str], cmd: str, field: SettingField) -> None:
        """Handle numeric input to view item details."""
        try:
            idx = int(cmd) - 1
            if 0 <= idx < len(items) and field.type == FieldType.PROVIDER_SELECT:
                self._show_provider_details(field, items[idx])
            elif not (0 <= idx < len(items)):
                print("Invalid index")
        except ValueError:
            print("Unknown command")

    def edit_list_field(self, namespace: str, key: str) -> None:
        """Interactive list editor for LIST/PROVIDER_SELECT fields.

        Args:
            namespace: The namespace.
            key: The field key.
        """
        field = self._settings.get_field(namespace, key)
        if not field:
            print(f"Error: Field '{key}' not found")
            return

        if field.type not in (FieldType.LIST, FieldType.PROVIDER_SELECT):
            print(f"Error: Field '{key}' is not a list type")
            return

        current = self.get_value(namespace, key)
        items = (
            list(current) if isinstance(current, list)
            else ([current] if current else [])
        )

        print(f"\n═══ Edit: {field.label} ═══")
        self._print_list_items(items)

        print("\nCommands:")
        print("  1-N: View item details")
        print("  u N: Move item N up")
        print("  d N: Move item N down")
        print("  a:   Add new item")
        print("  r N: Remove item N")
        print("  q:   Done (saves to pending)")
        print("  x:   Cancel")

        while True:
            cmd = input("\n> ").strip().lower()

            if cmd == "q":
                self.set_value(namespace, key, items)
                print(f"Saved to pending: {' → '.join(items)}")
                break
            elif cmd == "x":
                print("Cancelled")
                break
            elif cmd == "a":
                self._list_cmd_add(items, field)
            elif cmd.startswith("u "):
                self._list_cmd_move_up(items, cmd)
                self._print_list_items(items)
            elif cmd.startswith("d "):
                self._list_cmd_move_down(items, cmd)
                self._print_list_items(items)
            elif cmd.startswith("r "):
                self._list_cmd_remove(items, cmd)
                self._print_list_items(items)
            else:
                self._list_cmd_view_detail(items, cmd, field)

    def _print_list_items(self, items: List[str]) -> None:
        """Print numbered list of items."""
        if not items:
            print("  (empty)")
            return

        for i, item in enumerate(items, 1):
            marker = "→" if i == 1 else " "
            print(f"  {i}. {marker} {item}")

    def _get_available_options(
        self, field: SettingField, current_items: List[str]
    ) -> List[str]:
        """Get options not already in list.

        Args:
            field: The field definition.
            current_items: Currently selected items.

        Returns:
            List of available options.
        """
        if field.options:
            return [opt for opt in field.options if opt not in current_items]

        if field.options_provider:
            all_opts = self._settings.get_options(field.options_provider)
            return [opt for opt in all_opts if opt not in current_items]

        # For PROVIDER_SELECT, try to get from registered namespaces
        if field.type == FieldType.PROVIDER_SELECT and field.provider_type:
            prefix = f"voice.{field.provider_type}."
            available = []
            for ns in self._settings.get_namespaces():
                if ns.name.startswith(prefix):
                    backend = ns.name.split(".")[-1]
                    if backend not in current_items:
                        available.append(backend)
            return available

        return []

    def _show_provider_details(self, field: SettingField, provider: str) -> None:
        """Show settings for a selected provider.

        Args:
            field: The provider select field.
            provider: The selected provider name.
        """
        if not field.provider_namespace_template:
            print(f"  Provider: {provider}")
            return

        namespace = field.provider_namespace_template.format(
            provider_type=field.provider_type,
            value=provider,
        )

        section = self.vm.get_section(namespace)
        if section:
            print(f"\n  ── {section.display_name} Settings ──")
            for group_name, fields in section.groups.items():
                for f in fields:
                    value = section.values.get(f.key, f.default)
                    display = self._render_field_value(f, value)
                    print(f"    {f.label}: {display}")
        else:
            print(f"  No settings registered for '{namespace}'")


def _cmd_set(cli: SettingsCLI, args: List[str]) -> int:
    """Handle the 'set' settings command."""
    if len(args) < 3:
        print("Usage: --settings set <namespace> <key> <value>")
        return 1
    value: Any = args[2]
    if value.startswith("[") and value.endswith("]"):
        value = [v.strip() for v in value[1:-1].split(",")]
    error = cli.set_value(args[0], args[1], value)
    if error:
        print(f"Error: {error}")
        return 1
    print(f"Buffered: {args[0]}.{args[1]} = {value}")
    return 0


def _require_args(args: List[str], count: int, usage: str) -> bool:
    """Check that args has at least count items, printing usage if not."""
    if len(args) < count:
        print(usage)
        return False
    return True


def run_settings_command(
    settings_manager: SettingsManager,
    command: str,
    args: List[str],
) -> int:
    """Run a settings CLI command.

    Args:
        settings_manager: The SettingsManager instance.
        command: Command name (list, show, get, set, apply, discard, edit).
        args: Command arguments.

    Returns:
        Exit code (0=success, 1=error).
    """
    cli = SettingsCLI(settings_manager)

    # No-arg commands
    if command == "list":
        cli.list_namespaces()
        return 0
    if command == "apply":
        return 1 if cli.apply_changes() else 0
    if command == "discard":
        cli.discard_changes()
        return 0
    if command == "interactive":
        print("Interactive mode not yet implemented")
        return 1
    if command == "set":
        return _cmd_set(cli, args)

    # Commands that need 1 arg
    if command == "show":
        if not _require_args(args, 1, "Usage: --settings show <namespace>"):
            return 1
        cli.show_namespace(args[0])
        return 0

    # Commands that need 2 args
    two_arg_cmds: dict[str, tuple[str, Any]] = {
        "get": (
            "Usage: --settings get <namespace> <key>",
            lambda: (
                print(cli.get_value(args[0], args[1])), 0
            )[1],
        ),
        "edit": (
            "Usage: --settings edit <namespace> <key>",
            lambda: (
                cli.edit_list_field(args[0], args[1]), 0
            )[1],
        ),
        "reset": (
            "Usage: --settings reset <namespace> <key>",
            lambda: (
                cli.reset_field(args[0], args[1]), 0
            )[1],
        ),
    }
    if command in two_arg_cmds:
        usage, handler = two_arg_cmds[command]
        if not _require_args(args, 2, usage):
            return 1
        return handler()

    print(f"Unknown settings command: {command}")
    print("Available: list, show, get, set, apply, discard, edit, reset")
    return 1
