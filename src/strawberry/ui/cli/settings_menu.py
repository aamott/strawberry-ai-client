"""CLI settings interface.

Provides an interactive menu for viewing and editing settings in the CLI.
"""

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from strawberry.shared.settings import SettingsManager, SettingsViewModel
    from strawberry.shared.settings.view_model import SettingsSection
    from strawberry.shared.settings.schema import SettingField

from . import renderer


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
                choice = input("Select section (number): ").strip()
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
                input("Press Enter to go back...")
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
                choice = input("Edit setting (number): ").strip()
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
            # Show the label for the current option if available
            options = field.options or []
            for opt in options:
                if opt.get("value") == value:
                    return opt.get("label", str(value))
            return str(value)

        return str(value)

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
        new_value = input("  > ").strip()
        return new_value if new_value else None

    def _edit_password(self, current: Any, label: str = "value") -> Optional[str]:
        """Edit a password field."""
        masked = "****" if current else "(not set)"
        print(f"  Current: {masked}")
        print()
        print(f"  Enter new {label} (empty to cancel):")
        new_value = input("  > ").strip()
        return new_value if new_value else None

    def _edit_checkbox(self, current: Any, label: str = "value") -> Optional[bool]:
        """Edit a checkbox field."""
        current_str = "Yes" if current else "No"
        new_str = "No" if current else "Yes"
        print(f"  Current: {current_str}")
        print()
        print(f"  Change to {new_str}? (y/n):")
        choice = input("  > ").strip().lower()
        if choice in ("y", "yes"):
            return not current
        return None

    def _edit_select(self, current: Any, options: list, label: str = "option") -> Optional[str]:
        """Edit a select field."""
        print(f"  Current: {current or '(not set)'}")
        print()
        print("  Available options:")
        for i, opt in enumerate(options, 1):
            marker = " <-- current" if opt.get("value") == current else ""
            print(f"    {i}. {opt.get('label', opt.get('value'))}{marker}")
        print()
        print(f"  Select new {label} (number, empty to cancel):")
        choice = input("  > ").strip()
        if not choice:
            return None

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return options[idx].get("value")
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
