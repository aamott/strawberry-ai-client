"""CLI settings editor for testing and scripting.

This module provides a command-line interface for viewing and editing settings,
designed to work alongside the CLI for rapid iteration before Qt UI implementation.
"""

from typing import Any, Dict, List, Optional

from strawberry.shared.settings import (
    FieldType,
    PendingChangeController,
    SettingField,
    SettingsManager,
    format_field_value,
    get_available_options,
    list_move_down,
    list_move_up,
    list_remove,
)


class SettingsCLI:
    """CLI settings editor using shared PendingChangeController.

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
        self._ctrl = PendingChangeController(settings_manager)
        self._settings = settings_manager

    @property
    def vm(self):
        """Access the underlying view model."""
        return self._ctrl.view_model

    @property
    def pending_changes(self):
        """Access pending changes dict (for backward compat)."""
        return self._ctrl._pending

    def list_namespaces(self) -> None:
        """List all registered settings namespaces."""
        sections = self._ctrl.view_model.get_sections()
        if not sections:
            print("No registered namespaces")
            return

        # Group by tab
        tabs: Dict[str, List] = {}
        for ns in sections:
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

    def _print_field(self, field: SettingField, value: Any, pending: Any = None) -> None:
        """Print a single field with its value.

        Args:
            field: The field definition.
            value: Current value.
            pending: Pending change value (if any).
        """
        display = format_field_value(field, value)

        # Show pending indicator
        if pending is not None:
            pending_display = format_field_value(field, pending)
            print(f"  {field.label}: {display} → {pending_display} [pending]")
        else:
            print(f"  {field.label}: {display}")

        # Show description on separate line if present
        if field.description:
            print(f"    └─ {field.description}")

    def get_value(self, namespace: str, key: str) -> Any:
        """Get current value (including pending changes).

        Args:
            namespace: The namespace.
            key: The field key.

        Returns:
            Current or pending value.
        """
        return self._ctrl.get_value(namespace, key)

    def set_value(self, namespace: str, key: str, value: Any) -> Optional[str]:
        """Buffer a value change (doesn't apply until apply_changes).

        Args:
            namespace: The namespace.
            key: The field key.
            value: The new value.

        Returns:
            Validation error message or None if valid.
        """
        return self._ctrl.set_value(namespace, key, value)

    def apply_changes(self) -> List[str]:
        """Apply all pending changes.

        Returns:
            List of error messages (empty if all succeeded).
        """
        errors = self._ctrl.apply()
        if not errors:
            print("✓ Changes applied and saved")
        else:
            print("✗ Some changes failed:")
            for err in errors:
                print(f"  - {err}")
        return errors

    def discard_changes(self) -> None:
        """Discard all pending changes."""
        count = self._ctrl.discard()
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

        current = self._ctrl.get_value(namespace, key)
        if current == field.default:
            print(f"{field.label} is already at default value")
            return

        error = self._ctrl.reset_field(namespace, key)
        if error:
            print(f"Error: {error}")
        else:
            print(f"{field.label}: {current} → {field.default} [pending reset]")

    def has_pending_changes(self) -> bool:
        """Check if there are pending changes."""
        return self._ctrl.has_pending()

    def get_pending_count(self) -> int:
        """Get the number of pending changes."""
        return self._ctrl.pending_count()

    def _list_cmd_add(self, items: list[str], field: SettingField) -> None:
        """Handle the 'add' command in the list editor."""
        available = get_available_options(self._settings, field, items)
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
            if not list_move_up(items, idx):
                print("Cannot move up")
        except (ValueError, IndexError):
            print("Invalid index")

    @staticmethod
    def _list_cmd_move_down(items: list[str], cmd: str) -> None:
        """Handle the 'd N' (move down) command."""
        try:
            idx = int(cmd[2:]) - 1
            if not list_move_down(items, idx):
                print("Cannot move down")
        except (ValueError, IndexError):
            print("Invalid index")

    @staticmethod
    def _list_cmd_remove(items: list[str], cmd: str) -> None:
        """Handle the 'r N' (remove) command."""
        try:
            idx = int(cmd[2:]) - 1
            removed = list_remove(items, idx)
            if removed is not None:
                print(f"Removed: {removed}")
            else:
                print("Invalid index")
        except (ValueError, IndexError):
            print("Invalid index")

    def _list_cmd_view_detail(
        self, items: list[str], cmd: str, field: SettingField
    ) -> None:
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
            list(current) if isinstance(current, list) else ([current] if current else [])
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
                    display = format_field_value(f, value)
                    print(f"    {f.label}: {display}")
        else:
            print(f"  No settings registered for '{namespace}'")


def _coerce_field_value(field: SettingField, raw: str) -> Optional[Any]:
    """Coerce a raw string input to the field's expected type.

    Args:
        field: The field definition.
        raw: Raw string input from user.

    Returns:
        Coerced value, or None if conversion failed (error printed).
    """
    if field.type == FieldType.CHECKBOX:
        return raw.lower() in ("true", "1", "yes", "on")
    if field.type in (FieldType.NUMBER, FieldType.SLIDER):
        try:
            return float(raw) if "." in raw else int(raw)
        except ValueError:
            print(f"  Error: '{raw}' is not a valid number")
            return None
    return raw


def _interactive_edit_field(
    cli: SettingsCLI, namespace: str, field: SettingField,
) -> None:
    """Prompt user to edit a single field value.

    Args:
        cli: The SettingsCLI instance.
        namespace: Settings namespace.
        field: The field to edit.
    """
    current = cli.get_value(namespace, field.key)
    display = format_field_value(field, current)
    print(f"\n  {field.label} [{field.type.value}]")
    if field.description:
        print(f"  {field.description}")
    print(f"  Current: {display}")

    if field.type == FieldType.SELECT and field.options:
        print(f"  Options: {', '.join(field.options)}")
    elif field.type == FieldType.CHECKBOX:
        print("  Enter: true/false")
    elif field.type in (FieldType.LIST, FieldType.PROVIDER_SELECT):
        cli.edit_list_field(namespace, field.key)
        return

    raw = input("  New value (enter to keep): ").strip()
    if not raw:
        return

    value = _coerce_field_value(field, raw)
    if value is None:
        return

    error = cli.set_value(namespace, field.key, value)
    if error:
        print(f"  Error: {error}")
    else:
        print(f"  Buffered: {field.label} → {value}")


def _interactive_namespace(cli: SettingsCLI, namespace: str) -> None:
    """Interactive editor for a single namespace.

    Args:
        cli: The SettingsCLI instance.
        namespace: The namespace to edit.
    """
    section = cli.vm.get_section(namespace)
    if not section:
        print(f"Error: Namespace '{namespace}' not found")
        return

    while True:
        # Show fields with numbered indices
        print(f"\n═══ {section.display_name} ({namespace}) ═══")
        fields_flat: List[SettingField] = []
        for group_name, fields in section.groups.items():
            print(f"\n── {group_name} ──")
            for field in fields:
                idx = len(fields_flat) + 1
                value = section.values.get(field.key, field.default)
                pending = cli.pending_changes.get(
                    namespace, {},
                ).get(field.key)
                display = format_field_value(field, value)
                marker = ""
                if pending is not None:
                    p_display = format_field_value(field, pending)
                    marker = f" → {p_display} [pending]"
                print(f"  {idx}. {field.label}: {display}{marker}")
                fields_flat.append(field)

        print("\nCommands: <N> edit field, (a)pply, (b)ack")
        cmd = input("> ").strip().lower()

        if cmd in ("b", "back", "q"):
            break
        elif cmd in ("a", "apply"):
            cli.apply_changes()
        elif cmd.isdigit():
            idx = int(cmd) - 1
            if 0 <= idx < len(fields_flat):
                _interactive_edit_field(
                    cli, namespace, fields_flat[idx],
                )
            else:
                print("Invalid field number")
        else:
            print("Unknown command")


def _print_namespace_list(cli: SettingsCLI) -> list:
    """Print numbered namespace list grouped by tab.

    Args:
        cli: The SettingsCLI instance.

    Returns:
        Flat list of namespace section objects in display order.
    """
    sections = cli.vm.get_sections()
    if not sections:
        print("No registered settings namespaces")
        return []

    tabs: dict[str, list] = {}
    for ns in sections:
        tabs.setdefault(ns.tab, []).append(ns)

    ns_list: list = []
    for tab_name, tab_ns in sorted(tabs.items()):
        print(f"── {tab_name} ──")
        for ns in sorted(tab_ns, key=lambda x: x.order):
            idx = len(ns_list) + 1
            count = len(ns.schema)
            print(f"  {idx}. {ns.display_name} ({count} fields)")
            ns_list.append(ns)
    return ns_list


def _run_interactive(cli: SettingsCLI) -> int:
    """Run an interactive settings browser/editor.

    Lets the user browse tabs → namespaces → fields, edit values,
    and apply changes, all from the terminal.

    Args:
        cli: The SettingsCLI instance.

    Returns:
        Exit code (0=success).
    """
    print("\n═══ Settings (interactive) ═══")
    print("Commands: <N> open namespace, (a)pply, (q)uit\n")

    while True:
        ns_list = _print_namespace_list(cli)
        if not ns_list:
            return 0

        pending = cli.get_pending_count()
        if pending:
            print(f"\n  [{pending} pending change(s)]")

        cmd = input("\n> ").strip().lower()

        if cmd in ("q", "quit", "exit"):
            if cli.has_pending_changes():
                confirm = input(
                    "Discard pending changes? (y/n): ",
                ).strip().lower()
                if confirm != "y":
                    continue
            print("Goodbye!")
            return 0
        elif cmd in ("a", "apply"):
            cli.apply_changes()
        elif cmd.isdigit():
            idx = int(cmd) - 1
            if 0 <= idx < len(ns_list):
                _interactive_namespace(cli, ns_list[idx].name)
            else:
                print("Invalid selection")
        else:
            print(
                "Unknown command. Enter a number, (a)pply, or (q)uit.",
            )


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
        return _run_interactive(cli)
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
            lambda: (print(cli.get_value(args[0], args[1])), 0)[1],
        ),
        "edit": (
            "Usage: --settings edit <namespace> <key>",
            lambda: (cli.edit_list_field(args[0], args[1]), 0)[1],
        ),
        "reset": (
            "Usage: --settings reset <namespace> <key>",
            lambda: (cli.reset_field(args[0], args[1]), 0)[1],
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
