"""CLI settings interface.

Provides an interactive menu for viewing and editing settings in the CLI.
"""

import sys
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from strawberry.shared.settings import SettingsManager, SettingsViewModel
    from strawberry.shared.settings.view_model import SettingsSection
    from strawberry.shared.settings.schema import SettingField

from . import renderer


def _prompt(text: str) -> str:
    """Display a prompt and get user input, ensuring proper flushing."""
    sys.stdout.write(text)
    sys.stdout.flush()
    return input().strip()


class CLISettingsMenu:
    """CLI settings interface using simple text prompts."""

    def __init__(self, settings_manager: "SettingsManager"):
        """Initialize the settings menu.

        Args:
            settings_manager: The SettingsManager to read/write settings.
        """
        self._settings = settings_manager
        self._view_model: Optional["SettingsViewModel"] = None

    def _get_view_model(self) -> "SettingsViewModel":
        """Lazy-load the view model."""
        if self._view_model is None:
            from strawberry.shared.settings import SettingsViewModel

            self._view_model = SettingsViewModel(self._settings)
        return self._view_model

    def show(self) -> None:
        """Show the main settings menu."""
        vm = self._get_view_model()
        sections = vm.get_sections()

        if not sections:
            renderer.print_system("No settings registered.")
            return

        while True:
            print("\n" + "=" * 50)
            print("  SETTINGS")
            print("=" * 50)

            # List namespaces (sections are SettingsSection dataclass objects)
            for i, section in enumerate(sections, 1):
                print(f"  {i}. {section.display_name}")

            print(f"  {len(sections) + 1}. Back")
            print()

            try:
                choice = _prompt("Select section (number): ")
                if not choice:
                    continue

                idx = int(choice) - 1
                if idx == len(sections):
                    # Back
                    return
                if 0 <= idx < len(sections):
                    self._show_section(sections[idx])
            except ValueError:
                renderer.print_error("Please enter a number")
            except (EOFError, KeyboardInterrupt):
                print()
                return

    def _show_section(self, section: "SettingsSection") -> None:
        """Show settings for a specific section/namespace."""
        namespace = section.namespace
        display_name = section.display_name

        while True:
            print("\n" + "-" * 50)
            print(f"  {display_name}")
            print("-" * 50)

            # section.groups is Dict[str, List[SettingField]]
            if not section.groups:
                renderer.print_system("No settings in this section.")
                _prompt("Press Enter to go back...")
                return

            # Display fields with numbers
            field_list: list[tuple[str, str, "SettingField"]] = []
            idx = 1
            for group_name, group_fields in section.groups.items():
                print(f"\n  [{group_name}]")
                for field in group_fields:
                    key = field.key
                    label = field.label or key
                    value = self._settings.get(namespace, key)
                    display_value = self._format_value(value, field)

                    print(f"    {idx}. {label}: {display_value}")
                    field_list.append((namespace, key, field))
                    idx += 1

            print(f"\n    {idx}. Back")
            print()

            try:
                choice = _prompt("Edit setting (number): ")
                if not choice:
                    continue

                choice_idx = int(choice) - 1
                if choice_idx == len(field_list):
                    # Back
                    return
                if 0 <= choice_idx < len(field_list):
                    ns, key, field = field_list[choice_idx]
                    self._edit_field(ns, key, field)
            except ValueError:
                renderer.print_error("Please enter a number")
            except (EOFError, KeyboardInterrupt):
                print()
                return

    def _format_value(self, value: Any, field: "SettingField") -> str:
        """Format a value for display."""
        from strawberry.shared.settings.schema import FieldType

        field_type = field.type

        if value is None:
            return "(not set)"

        if field_type == FieldType.PASSWORD:
            # Mask passwords
            if value:
                return "****" + str(value)[-4:] if len(str(value)) > 4 else "****"
            return "(not set)"

        if field_type == FieldType.CHECKBOX:
            return "Yes" if value else "No"

        if field_type == FieldType.SELECT:
            # Options are plain strings (List[str]) in the schema
            # Just return the value as-is since it should match an option
            return str(value)

        return str(value)

    def _get_backend_options(self, key: str) -> list[str]:
        """Get available backend options for order fields.
        
        Args:
            key: The setting key (e.g., "stt.order", "tts.order")
            
        Returns:
            List of available backend names, or empty list if not applicable.
        """
        if not key.endswith(".order"):
            return []
        
        try:
            # Determine which type of backend based on key prefix
            if key.startswith("stt."):
                from strawberry.voice.stt import discover_stt_modules
                return list(discover_stt_modules().keys())
            elif key.startswith("tts."):
                from strawberry.voice.tts import discover_tts_modules
                return list(discover_tts_modules().keys())
            elif key.startswith("vad."):
                from strawberry.voice.vad import discover_vad_modules
                return list(discover_vad_modules().keys())
            elif key.startswith("wakeword."):
                from strawberry.voice.wakeword import discover_wake_modules
                return list(discover_wake_modules().keys())
        except ImportError:
            pass
        
        return []

    def _edit_field(self, namespace: str, key: str, field: "SettingField") -> None:
        """Edit a single field."""
        from strawberry.shared.settings.schema import FieldType

        field_type = field.type
        label = field.label or key
        current = self._settings.get(namespace, key)

        print(f"\n  Editing: {label}")
        if field.description:
            print(f"  {field.description}")

        try:
            if field_type == FieldType.CHECKBOX:
                new_value = self._edit_checkbox(current, label)
            elif field_type == FieldType.SELECT:
                new_value = self._edit_select(current, field.options or [], label)
            elif field_type == FieldType.PASSWORD:
                new_value = self._edit_password(current, label)
            elif field_type == FieldType.ACTION:
                # Actions are not editable
                renderer.print_system("Action fields cannot be edited here.")
                return
            else:
                # Check if this is a backend order field
                backend_options = self._get_backend_options(key)
                if backend_options:
                    new_value = self._edit_backend_order(current, backend_options, label)
                else:
                    new_value = self._edit_text(current, label)

            if new_value is not None:
                self._settings.set(namespace, key, new_value)
                renderer.print_system(f"Updated {label}")

        except (EOFError, KeyboardInterrupt):
            print()
            renderer.print_system("Cancelled")

    def _edit_text(self, current: Any, label: str = "value") -> Optional[str]:
        """Edit a text field."""
        print(f"  Current: {current or '(not set)'}")
        print()
        print(f"  Enter new {label} (empty to cancel):")
        new_value = _prompt("  > ")
        return new_value if new_value else None

    def _edit_backend_order(
        self, current: Any, available: list[str], label: str = "order"
    ) -> Optional[str]:
        """Edit a backend order field with available options shown.
        
        Args:
            current: Current comma-separated value
            available: List of available backend names
            label: Field label for prompts
            
        Returns:
            New comma-separated value, or None if cancelled
        """
        # Parse current order
        current_list = []
        if current:
            current_list = [b.strip() for b in str(current).split(",") if b.strip()]
        
        print(f"  Current: {current or '(not set)'}")
        print()
        print("  Available backends:")
        for i, backend in enumerate(available, 1):
            in_current = backend in current_list
            marker = " <-- in current order" if in_current else ""
            print(f"    {i}. {backend}{marker}")
        
        print()
        print("  Enter new order as comma-separated list (e.g., '1,3' or 'pocket,orca')")
        print("  Or type backend names directly. Empty to cancel:")
        choice = _prompt("  > ")
        
        if not choice:
            return None
        
        # Parse the input - could be numbers or names
        parts = [p.strip() for p in choice.split(",") if p.strip()]
        result = []
        
        for part in parts:
            # Try as number first
            try:
                idx = int(part) - 1
                if 0 <= idx < len(available):
                    result.append(available[idx])
                    continue
            except ValueError:
                pass
            
            # Try as backend name (case-insensitive match)
            part_lower = part.lower()
            for backend in available:
                if backend.lower() == part_lower:
                    result.append(backend)
                    break
            else:
                # Not found - use as-is (might be a new/unknown backend)
                result.append(part)
        
        if result:
            return ",".join(result)
        
        renderer.print_error("No valid backends selected")
        return None

    def _edit_password(self, current: Any, label: str = "value") -> Optional[str]:
        """Edit a password field."""
        masked = "****" if current else "(not set)"
        print(f"  Current: {masked}")
        print()
        print(f"  Enter new {label} (empty to cancel):")
        new_value = _prompt("  > ")
        return new_value if new_value else None

    def _edit_checkbox(self, current: Any, label: str = "value") -> Optional[bool]:
        """Edit a checkbox field."""
        current_str = "Yes" if current else "No"
        new_str = "No" if current else "Yes"
        print(f"  Current: {current_str}")
        print()
        print(f"  Change to {new_str}? (y/n):")
        choice = _prompt("  > ").lower()
        if choice in ("y", "yes"):
            return not current
        return None

    def _edit_select(self, current: Any, options: list, label: str = "option") -> Optional[str]:
        """Edit a select field.
        
        Options are plain strings (List[str]) in the schema.
        """
        print(f"  Current: {current or '(not set)'}")
        print()
        print("  Available options:")
        for i, opt in enumerate(options, 1):
            # Options are strings, not dicts
            marker = " <-- current" if opt == current else ""
            print(f"    {i}. {opt}{marker}")
        print()
        print(f"  Select new {label} (number, empty to cancel):")
        choice = _prompt("  > ")
        if not choice:
            return None

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return options[idx]  # Return the string directly
        except ValueError:
            pass

        renderer.print_error("Invalid option")
        return None

    def show_summary(self) -> None:
        """Show a quick summary of key settings (for /status command)."""
        vm = self._get_view_model()
        sections = vm.get_sections()

        print("\n  Key Settings:")
        for section in sections:
            namespace = section.namespace

            # Show first few important fields from each group
            shown = 0
            for group_name, group_fields in section.groups.items():
                for field in group_fields:
                    if shown >= 2:
                        break
                    value = self._settings.get(namespace, field.key)
                    if value is not None:
                        label = field.label or field.key
                        display = self._format_value(value, field)
                        print(f"    {section.display_name}.{label}: {display}")
                        shown += 1
