"""Fully-featured interactive CLI settings menu.

Provides a rich terminal UI for browsing, editing, and applying settings
with ANSI colors, type-specific field editors, breadcrumb navigation,
search, pending-changes diff view, and reset-to-default support.

Usage:
    python -m strawberry.ui.test_cli --settings interactive
"""

from __future__ import annotations

import getpass
import os
import re
import sys
from typing import Any, Dict, List, Optional

from strawberry.shared.settings import (
    FieldType,
    PendingChangeController,
    SettingField,
    SettingsManager,
    SettingsSection,
    format_field_value,
    get_available_options,
    list_move_down,
    list_move_up,
    list_remove,
)

# ── ANSI color helpers ──────────────────────────────────────────────


def _supports_color() -> bool:
    """Detect whether the terminal supports ANSI color."""
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(sys.stdout, "isatty"):
        return False
    return sys.stdout.isatty()


_COLOR = _supports_color()


def _c(code: str, text: str) -> str:
    """Wrap *text* in an ANSI escape if color is supported."""
    if not _COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


# Semantic color shortcuts
def _dim(t: str) -> str:
    return _c("2", t)


def _bold(t: str) -> str:
    return _c("1", t)


def _cyan(t: str) -> str:
    return _c("36", t)


def _green(t: str) -> str:
    return _c("32", t)


def _yellow(t: str) -> str:
    return _c("33", t)


def _red(t: str) -> str:
    return _c("31", t)


def _magenta(t: str) -> str:
    return _c("35", t)


# Box-drawing
_H = "─"  # horizontal
_V = "│"  # vertical
_TL = "┌"
_TR = "┐"
_BL = "└"
_BR = "┘"


def _box_title(title: str, width: int = 60) -> str:
    """Render a top-bordered title bar."""
    inner = f" {title} "
    pad = width - len(inner) - 2
    left = pad // 2
    right = pad - left
    return _cyan(f"{_TL}{_H * left}{inner}{_H * right}{_TR}")


def _box_bottom(width: int = 60) -> str:
    return _cyan(f"{_BL}{_H * width}{_BR}")


def _separator(char: str = _H, width: int = 60) -> str:
    return _dim(char * width)


# ── Input helpers ───────────────────────────────────────────────────


def _prompt(label: str = "> ", default: str = "") -> str:
    """Read a line of input with a styled prompt.

    Args:
        label: Prompt text.
        default: Shown in dim brackets if non-empty.

    Returns:
        Stripped user input, or empty string on EOF.
    """
    hint = f" {_dim(f'[{default}]')}" if default else ""
    try:
        return input(f"{_cyan(label)}{hint} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


def _confirm(question: str, default: bool = False) -> bool:
    """Ask a yes/no question.

    Args:
        question: Question text.
        default: Default answer if user presses Enter.

    Returns:
        True for yes, False for no.
    """
    suffix = "(Y/n)" if default else "(y/N)"
    ans = _prompt(f"{question} {suffix}")
    if not ans:
        return default
    return ans.lower() in ("y", "yes")


# ── Type badge ──────────────────────────────────────────────────────


_TYPE_BADGES: Dict[FieldType, str] = {
    FieldType.TEXT: "TXT",
    FieldType.PASSWORD: "KEY",
    FieldType.NUMBER: "NUM",
    FieldType.CHECKBOX: "CHK",
    FieldType.SELECT: "SEL",
    FieldType.DYNAMIC_SELECT: "DYN",
    FieldType.ACTION: "ACT",
    FieldType.MULTILINE: "MLT",
    FieldType.PROVIDER_SELECT: "PRV",
    FieldType.LIST: "LST",
    FieldType.FILE_PATH: "FIL",
    FieldType.DIRECTORY_PATH: "DIR",
    FieldType.COLOR: "CLR",
    FieldType.SLIDER: "SLD",
    FieldType.DATE: "DAT",
    FieldType.TIME: "TIM",
    FieldType.DATETIME: "DTM",
}


def _type_badge(ft: FieldType) -> str:
    """Render a compact type badge like [SEL]."""
    label = _TYPE_BADGES.get(ft, ft.value[:3].upper())
    return _dim(f"[{label}]")


# ── Status bar ──────────────────────────────────────────────────────


def _status_bar(ctrl: PendingChangeController) -> str:
    """Render a one-line status bar showing pending count."""
    n = ctrl.pending_count()
    if n == 0:
        return ""
    return _yellow(f"  ● {n} pending change{'s' if n != 1 else ''}")


# ── Field value rendering (enhanced) ───────────────────────────────


def _render_value(
    field: SettingField,
    value: Any,
    pending: Any = None,
) -> str:
    """Render a field value, highlighting pending changes.

    Args:
        field: Field schema.
        value: Current stored value.
        pending: Buffered pending value, if any.

    Returns:
        Formatted string.
    """
    display = format_field_value(field, value)
    if pending is not None:
        p_display = format_field_value(field, pending)
        return f"{_dim(display)} → {_yellow(p_display)}"
    return display


# ═══════════════════════════════════════════════════════════════════
# Type-specific field editors
# ═══════════════════════════════════════════════════════════════════


def _edit_text(field: SettingField, current: Any) -> Optional[str]:
    """Edit a TEXT field. Returns new value or None to cancel."""
    if field.placeholder:
        print(f"  {_dim(f'Placeholder: {field.placeholder}')}")
    raw = _prompt("  New value:", str(current or ""))
    return raw if raw else None


def _edit_password(field: SettingField, current: Any) -> Optional[str]:
    """Edit a PASSWORD field with masked input."""
    has_value = bool(current)
    if has_value:
        print(f"  {_dim('Current: ••••••••')}")
    try:
        raw = getpass.getpass("  New value (hidden): ")
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    return raw.strip() if raw.strip() else None


def _edit_number(field: SettingField, current: Any) -> Optional[Any]:
    """Edit a NUMBER field with range validation."""
    range_str = ""
    if field.min_value is not None or field.max_value is not None:
        lo = field.min_value if field.min_value is not None else "-∞"
        hi = field.max_value if field.max_value is not None else "∞"
        range_str = f" {_dim(f'Range: {lo}..{hi}')}"
    print(f"  Current: {current}{range_str}")
    raw = _prompt("  New value:")
    if not raw:
        return None
    try:
        val = float(raw) if "." in raw else int(raw)
    except ValueError:
        print(_red(f"  Error: '{raw}' is not a valid number"))
        return None
    # Range check
    if field.min_value is not None and val < field.min_value:
        print(_red(f"  Error: minimum is {field.min_value}"))
        return None
    if field.max_value is not None and val > field.max_value:
        print(_red(f"  Error: maximum is {field.max_value}"))
        return None
    return val


def _edit_checkbox(field: SettingField, current: Any) -> bool:
    """Toggle a CHECKBOX field."""
    new_val = not bool(current)
    state = _green("[x]") if new_val else _dim("[ ]")
    print(f"  Toggled → {state}")
    return new_val


def _edit_select(
    field: SettingField, current: Any, settings: SettingsManager,
) -> Optional[str]:
    """Edit a SELECT or DYNAMIC_SELECT field with numbered picker."""
    options = list(field.options or [])
    if field.type == FieldType.DYNAMIC_SELECT and field.options_provider:
        options = settings.get_options(field.options_provider)
    if not options:
        print(_dim("  No options available"))
        return _edit_text(field, current)

    print(f"  Current: {_bold(str(current))}")
    for i, opt in enumerate(options, 1):
        marker = _green("●") if opt == str(current) else " "
        print(f"  {marker} {i}. {opt}")

    raw = _prompt("  Select number:")
    if not raw:
        return None
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(options):
            return options[idx]
        print(_red("  Invalid selection"))
        return None
    except ValueError:
        # Allow typing the value directly
        if raw in options:
            return raw
        print(_red(f"  '{raw}' is not a valid option"))
        return None


def _edit_multiline(field: SettingField, current: Any) -> Optional[str]:
    """Edit a MULTILINE field (end with empty line)."""
    print(f"  {_dim('Enter text (empty line to finish):')}")
    if current:
        print(f"  {_dim(f'Current: {str(current)[:60]}...')}")
    lines: list[str] = []
    while True:
        try:
            line = input("  │ ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line and lines:
            break
        lines.append(line)
    return "\n".join(lines) if lines else None


def _edit_slider(field: SettingField, current: Any) -> Optional[float]:
    """Edit a SLIDER field with visual range bar."""
    lo = field.min_value if field.min_value is not None else 0.0
    hi = field.max_value if field.max_value is not None else 1.0
    step = (field.metadata or {}).get("step", 0.1)
    cur = float(current) if current is not None else lo

    # Render a visual bar
    bar_width = 30
    ratio = (cur - lo) / (hi - lo) if hi != lo else 0
    filled = int(ratio * bar_width)
    bar = _green("█" * filled) + _dim("░" * (bar_width - filled))
    print(f"  {lo} {bar} {hi}  ({_bold(str(cur))})")
    print(f"  {_dim(f'Step: {step}')}")

    raw = _prompt("  New value:")
    if not raw:
        return None
    try:
        val = float(raw)
    except ValueError:
        print(_red(f"  Error: '{raw}' is not a number"))
        return None
    if val < lo or val > hi:
        print(_red(f"  Error: must be between {lo} and {hi}"))
        return None
    return val


def _edit_color(field: SettingField, current: Any) -> Optional[str]:
    """Edit a COLOR field with hex validation."""
    cur = current or "#000000"
    # Show a color swatch using ANSI 24-bit color if possible
    print(f"  Current: {_bold(cur)}")
    print(f"  {_dim('Format: #RRGGBB or #RRGGBBAA')}")
    raw = _prompt("  New color:")
    if not raw:
        return None
    if not re.match(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$", raw):
        print(_red("  Error: invalid hex color"))
        return None
    return raw


def _edit_file_path(field: SettingField, current: Any) -> Optional[str]:
    """Edit a FILE_PATH field with tilde/var expansion."""
    if current:
        print(f"  Current: {current}")
    must_exist = (field.metadata or {}).get("must_exist", False)
    raw = _prompt("  File path:")
    if not raw:
        return None
    expanded = os.path.expanduser(os.path.expandvars(raw))
    if must_exist and not os.path.isfile(expanded):
        print(_red(f"  Warning: file does not exist: {expanded}"))
        if not _confirm("  Keep anyway?"):
            return None
    return expanded


def _edit_directory_path(
    field: SettingField, current: Any,
) -> Optional[str]:
    """Edit a DIRECTORY_PATH field."""
    if current:
        print(f"  Current: {current}")
    raw = _prompt("  Directory path:")
    if not raw:
        return None
    expanded = os.path.expanduser(os.path.expandvars(raw))
    create = (field.metadata or {}).get("create_if_missing", False)
    if not os.path.isdir(expanded):
        if create and _confirm(f"  Create {expanded}?"):
            os.makedirs(expanded, exist_ok=True)
            print(_green(f"  Created: {expanded}"))
        else:
            print(_yellow("  Warning: directory does not exist"))
    return expanded


def _edit_date(field: SettingField, current: Any) -> Optional[str]:
    """Edit a DATE field (YYYY-MM-DD)."""
    print(f"  {_dim('Format: YYYY-MM-DD')}")
    if current:
        print(f"  Current: {current}")
    raw = _prompt("  Date:")
    if not raw:
        return None
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        print(_red("  Error: use YYYY-MM-DD format"))
        return None
    return raw


def _edit_time(field: SettingField, current: Any) -> Optional[str]:
    """Edit a TIME field (HH:MM)."""
    print(f"  {_dim('Format: HH:MM')}")
    if current:
        print(f"  Current: {current}")
    raw = _prompt("  Time:")
    if not raw:
        return None
    if not re.match(r"^\d{2}:\d{2}$", raw):
        print(_red("  Error: use HH:MM format"))
        return None
    return raw


def _edit_datetime(field: SettingField, current: Any) -> Optional[str]:
    """Edit a DATETIME field (YYYY-MM-DD HH:MM)."""
    fmt = (field.metadata or {}).get(
        "display_format", "YYYY-MM-DD HH:MM",
    )
    print(f"  {_dim(f'Format: {fmt}')}")
    if current:
        print(f"  Current: {current}")
    raw = _prompt("  DateTime:")
    if not raw:
        return None
    # Basic validation
    if not re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}", raw):
        print(_red(f"  Error: use {fmt} format"))
        return None
    return raw


# ═══════════════════════════════════════════════════════════════════
# Interactive Settings Menu
# ═══════════════════════════════════════════════════════════════════


class InteractiveSettingsMenu:
    """Fully-featured interactive settings browser and editor.

    Provides tab/namespace/field navigation with ANSI colors,
    type-specific editors, search, pending-changes diff, and
    reset-to-default support.

    Args:
        settings_manager: The SettingsManager instance.
    """

    def __init__(self, settings_manager: SettingsManager) -> None:
        self._settings = settings_manager
        self._ctrl = PendingChangeController(settings_manager)
        self._breadcrumb: list[str] = ["Settings"]

    # ── Breadcrumb ──────────────────────────────────────────────

    def _show_breadcrumb(self) -> None:
        """Print the current breadcrumb path."""
        path = " > ".join(self._breadcrumb)
        print(f"\n{_dim(path)}")

    # ── Global commands ─────────────────────────────────────────

    def _handle_global(self, cmd: str) -> bool:
        """Handle commands available at every navigation level.

        Args:
            cmd: Lowercased user input.

        Returns:
            True if the command was handled.
        """
        if cmd in ("h", "help", "?"):
            self._show_help()
            return True
        if cmd in ("p", "pending"):
            self._show_pending()
            return True
        if cmd in ("a", "apply"):
            self._do_apply()
            return True
        if cmd in ("d", "discard"):
            self._do_discard()
            return True
        if cmd.startswith("s ") or cmd.startswith("search "):
            query = cmd.split(None, 1)[1] if " " in cmd else ""
            self._do_search(query)
            return True
        return False

    def _show_help(self) -> None:
        """Print help for the current context."""
        print(f"\n{_box_title('Help', 50)}")
        cmds = [
            ("N", "Select item by number"),
            ("b / back", "Go back one level"),
            ("h / help", "Show this help"),
            ("a / apply", "Apply pending changes"),
            ("d / discard", "Discard pending changes"),
            ("p / pending", "Show pending changes diff"),
            ("s <query>", "Search fields by name/key"),
            ("q / quit", "Exit settings menu"),
        ]
        for key, desc in cmds:
            print(f"  {_cyan(key):18s} {desc}")
        print(_box_bottom(50))

    # ── Pending changes ─────────────────────────────────────────

    def _show_pending(self) -> None:
        """Show all pending changes as a diff view."""
        pending = self._ctrl._pending
        if not any(pending.values()):
            print(_dim("\n  No pending changes"))
            return

        print(f"\n{_box_title('Pending Changes', 56)}")
        for ns, changes in pending.items():
            if not changes:
                continue
            ns_obj = self._settings.get_namespace(ns)
            display = ns_obj.display_name if ns_obj else ns
            print(f"  {_bold(display)} {_dim(f'({ns})')}")
            for key, new_val in changes.items():
                field = self._settings.get_field(ns, key)
                if not field:
                    continue
                old_val = self._settings.get(ns, key)
                old_disp = format_field_value(field, old_val)
                new_disp = format_field_value(field, new_val)
                print(
                    f"    {field.label}: "
                    f"{_red(old_disp)} → {_green(new_disp)}",
                )
        print(_box_bottom(56))

    def _do_apply(self) -> None:
        """Apply changes with confirmation diff."""
        if not self._ctrl.has_pending():
            print(_dim("  No pending changes to apply"))
            return
        self._show_pending()
        if not _confirm("\n  Apply these changes?", default=True):
            return
        errors = self._ctrl.apply()
        if not errors:
            print(_green("  ✓ All changes applied and saved"))
        else:
            print(_red("  ✗ Some changes failed:"))
            for err in errors:
                print(f"    {_red(err)}")

    def _do_discard(self) -> None:
        """Discard pending changes with confirmation."""
        if not self._ctrl.has_pending():
            print(_dim("  No pending changes"))
            return
        count = self._ctrl.pending_count()
        if _confirm(f"  Discard {count} change(s)?"):
            self._ctrl.discard()
            print(_green("  ✓ Changes discarded"))

    # ── Search ──────────────────────────────────────────────────

    def _do_search(self, query: str) -> None:
        """Search fields across all namespaces.

        Args:
            query: Search string (case-insensitive substring match).
        """
        if not query:
            query = _prompt("  Search:")
        if not query:
            return

        q = query.lower()
        results: list[tuple[str, str, SettingField, Any]] = []

        for ns in self._settings.get_namespaces():
            for field in ns.schema:
                searchable = (
                    f"{field.key} {field.label} "
                    f"{field.description or ''} {ns.display_name}"
                ).lower()
                if q in searchable:
                    val = self._ctrl.get_value(ns.name, field.key)
                    results.append((ns.name, ns.display_name, field, val))

        if not results:
            print(_dim(f"  No fields matching '{query}'"))
            return

        print(f"\n{_box_title(f'Search: {query}', 56)}")
        for i, (ns, ns_disp, field, val) in enumerate(results, 1):
            pending = self._ctrl.get_pending_for(ns, field.key)
            v = _render_value(field, val, pending)
            badge = _type_badge(field.type)
            print(
                f"  {i}. {badge} {_bold(field.label)}: {v}"
                f"  {_dim(f'({ns_disp})')}"
            )
        print(_box_bottom(56))

        # Allow editing from search results
        raw = _prompt("  Edit # (or enter to go back):")
        if raw and raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(results):
                ns, _, field, _ = results[idx]
                self._edit_field(ns, field)

    # ── Field editing ───────────────────────────────────────────

    def _edit_field(self, namespace: str, field: SettingField) -> None:
        """Open the type-specific editor for a field.

        Args:
            namespace: Settings namespace.
            field: The field to edit.
        """
        current = self._ctrl.get_value(namespace, field.key)
        print(f"\n  {_bold(field.label)} {_type_badge(field.type)}")
        if field.description:
            print(f"  {_dim(field.description)}")

        new_val = self._dispatch_editor(field, current)
        if new_val is None:
            print(_dim("  (no change)"))
            return

        error = self._ctrl.set_value(namespace, field.key, new_val)
        if error:
            print(_red(f"  Validation error: {error}"))
        else:
            disp = format_field_value(field, new_val)
            print(_yellow(f"  Buffered: {field.label} → {disp}"))

    def _dispatch_editor(
        self, field: SettingField, current: Any,
    ) -> Any:
        """Route to the correct type-specific editor.

        Args:
            field: The field schema.
            current: Current value.

        Returns:
            New value, or None to cancel.
        """
        # Build dispatch table (simple editors keyed by FieldType)
        simple: dict[FieldType, Any] = {
            FieldType.TEXT: _edit_text,
            FieldType.PASSWORD: _edit_password,
            FieldType.NUMBER: _edit_number,
            FieldType.CHECKBOX: _edit_checkbox,
            FieldType.MULTILINE: _edit_multiline,
            FieldType.SLIDER: _edit_slider,
            FieldType.COLOR: _edit_color,
            FieldType.FILE_PATH: _edit_file_path,
            FieldType.DIRECTORY_PATH: _edit_directory_path,
            FieldType.DATE: _edit_date,
            FieldType.TIME: _edit_time,
            FieldType.DATETIME: _edit_datetime,
        }
        editor = simple.get(field.type)
        if editor:
            return editor(field, current)

        # Editors needing extra args
        if field.type in (FieldType.SELECT, FieldType.DYNAMIC_SELECT):
            return _edit_select(field, current, self._settings)
        if field.type in (FieldType.LIST, FieldType.PROVIDER_SELECT):
            return self._edit_list(
                namespace="", field=field, current=current,
            )
        if field.type == FieldType.ACTION:
            print(_dim("  (actions are not editable from CLI)"))
            return None
        # Fallback: text editor
        return _edit_text(field, current)

    def _list_cmd_add(
        self, items: list, field: SettingField,
    ) -> None:
        """Handle the 'add' command inside the list editor."""
        avail = get_available_options(self._settings, field, items)
        if avail:
            print("  Available:")
            for i, opt in enumerate(avail, 1):
                print(f"    {i}. {opt}")
            raw = _prompt("  Select # or type value:")
            try:
                idx = int(raw) - 1
                if 0 <= idx < len(avail):
                    items.append(avail[idx])
            except ValueError:
                if raw:
                    items.append(raw)
        else:
            raw = _prompt("  New item:")
            if raw:
                items.append(raw)

    @staticmethod
    def _list_cmd_reorder(
        items: list, cmd: str,
    ) -> None:
        """Handle move-up, move-down, and remove in list editor."""
        op = cmd[0]  # 'r', 'u', or 'd'
        try:
            idx = int(cmd[2:]) - 1
            if op == "r":
                removed = list_remove(items, idx)
                if removed:
                    print(_dim(f"  Removed: {removed}"))
            elif op == "u":
                list_move_up(items, idx)
            elif op == "d":
                list_move_down(items, idx)
        except (ValueError, IndexError):
            print(_red("  Invalid index"))

    def _edit_list(
        self, namespace: str, field: SettingField, current: Any,
    ) -> Optional[list]:
        """Interactive list editor for LIST/PROVIDER_SELECT fields.

        Args:
            namespace: Settings namespace.
            field: The field schema.
            current: Current value.

        Returns:
            New list value, or None to cancel.
        """
        items = (
            list(current)
            if isinstance(current, list)
            else ([current] if current else [])
        )
        print(f"\n  {_bold('List Editor')}")
        self._print_list(items)
        print(_dim(
            "  Commands: a=add, r N=remove, u N=up,"
            " d N=down, q=done, x=cancel"
        ))

        while True:
            cmd = _prompt("  list>")
            if cmd == "q":
                return items
            if cmd == "x":
                return None
            if cmd == "a":
                self._list_cmd_add(items, field)
            elif cmd[:2] in ("r ", "u ", "d "):
                self._list_cmd_reorder(items, cmd)
            self._print_list(items)

    @staticmethod
    def _print_list(items: list) -> None:
        """Print a numbered list of items."""
        if not items:
            print(_dim("  (empty)"))
            return
        for i, item in enumerate(items, 1):
            marker = _green("→") if i == 1 else " "
            print(f"  {marker} {i}. {item}")

    # ── Navigation screens ──────────────────────────────────────

    def _render_home_list(self) -> list[SettingsSection]:
        """Render the home screen namespace list and return flat list."""
        sections = self._ctrl.view_model.get_sections()
        if not sections:
            print(_dim("  No registered settings"))
            return []

        tabs: Dict[str, List[SettingsSection]] = {}
        for sec in sections:
            tabs.setdefault(sec.tab, []).append(sec)

        ns_flat: list[SettingsSection] = []
        self._show_breadcrumb()
        print(_box_title("Settings", 56))

        for tab_name, tab_sections in sorted(tabs.items()):
            print(f"\n  {_bold(tab_name)}")
            for sec in sorted(tab_sections, key=lambda s: s.order):
                idx = len(ns_flat) + 1
                count = len(sec.schema) if sec.schema else 0
                pending_ns = self._ctrl._pending.get(
                    sec.namespace, {},
                )
                p_mark = _yellow(" ●") if pending_ns else ""
                print(
                    f"    {idx}. {sec.display_name}"
                    f" {_dim(f'({count} fields)')}{p_mark}"
                )
                ns_flat.append(sec)

        status = _status_bar(self._ctrl)
        if status:
            print(f"\n{status}")
        print(_box_bottom(56))
        print(_dim(
            "  <N> open, (a)pply, (p)ending,"
            " (s) search, (h)elp, (q)uit"
        ))
        return ns_flat

    def _handle_home_input(
        self, cmd: str, ns_flat: list[SettingsSection],
    ) -> bool:
        """Handle a command on the home screen.

        Returns True to redraw, False to keep prompting.
        """
        if cmd in ("q", "quit", "exit"):
            if self._ctrl.has_pending():
                if not _confirm("  Discard pending changes?"):
                    return False
            raise _ExitMenu
        if cmd in ("b", "back"):
            return True
        if self._handle_global(cmd):
            return True
        if cmd.isdigit():
            idx = int(cmd) - 1
            if 0 <= idx < len(ns_flat):
                sec = ns_flat[idx]
                self._breadcrumb.append(sec.display_name)
                self._screen_namespace(sec.namespace)
                self._breadcrumb.pop()
                return True
            print(_red("  Invalid selection"))
        else:
            print(_dim("  Unknown command. Press h for help."))
        return False

    def _screen_home(self) -> None:
        """Top-level screen: tabs and namespaces."""
        ns_flat = self._render_home_list()
        if not ns_flat:
            return
        while True:
            cmd = _prompt(">").lower()
            if not cmd or self._handle_home_input(cmd, ns_flat):
                return

    def _render_ns_fields(
        self, namespace: str, section: SettingsSection,
    ) -> List[SettingField]:
        """Render namespace fields and return flat field list."""
        self._show_breadcrumb()
        print(_box_title(section.display_name, 56))

        fields_flat: List[SettingField] = []
        for group_name, fields in section.groups.items():
            print(f"\n  {_bold(group_name)}")
            for field in fields:
                idx = len(fields_flat) + 1
                value = section.values.get(field.key, field.default)
                pending = self._ctrl.get_pending_for(
                    namespace, field.key,
                )
                v = _render_value(field, value, pending)
                badge = _type_badge(field.type)
                print(f"    {idx}. {badge} {field.label}: {v}")
                if field.description:
                    print(f"       {_dim(field.description)}")
                fields_flat.append(field)

        status = _status_bar(self._ctrl)
        if status:
            print(f"\n{status}")
        print(_box_bottom(56))
        print(_dim(
            "  <N> edit, (r N) reset, (a)pply,"
            " (b)ack, (h)elp"
        ))
        return fields_flat

    def _handle_ns_input(
        self, cmd: str, namespace: str, fields: List[SettingField],
    ) -> bool:
        """Handle a command on the namespace screen.

        Returns True to redraw, False to keep prompting.
        """
        if cmd in ("b", "back"):
            raise _BackLevel
        if cmd in ("q", "quit"):
            raise _ExitMenu
        if self._handle_global(cmd):
            return True
        if cmd.startswith("r ") or cmd.startswith("reset "):
            self._do_reset_field(namespace, cmd, fields)
            return True
        if cmd.isdigit():
            idx = int(cmd) - 1
            if 0 <= idx < len(fields):
                field = fields[idx]
                self._breadcrumb.append(field.label)
                self._edit_field(namespace, field)
                self._breadcrumb.pop()
            else:
                print(_red("  Invalid field number"))
            return True
        print(_dim("  Unknown command. Press h for help."))
        return False

    def _screen_namespace(self, namespace: str) -> None:
        """Namespace detail screen: grouped fields."""
        try:
            while True:
                section = self._ctrl.view_model.get_section(namespace)
                if not section:
                    print(_red(f"  Namespace '{namespace}' not found"))
                    return
                fields = self._render_ns_fields(namespace, section)
                while True:
                    cmd = _prompt(">").lower()
                    if not cmd:
                        break  # redraw
                    if self._handle_ns_input(cmd, namespace, fields):
                        break  # redraw
        except _BackLevel:
            return

    def _do_reset_field(
        self,
        namespace: str,
        cmd: str,
        fields: List[SettingField],
    ) -> None:
        """Handle `r N` to reset a field to default.

        Args:
            namespace: Settings namespace.
            cmd: Raw command string like "r 3".
            fields: Flat list of fields in display order.
        """
        parts = cmd.split()
        if len(parts) < 2 or not parts[1].isdigit():
            print(_red("  Usage: r <field-number>"))
            return
        idx = int(parts[1]) - 1
        if not (0 <= idx < len(fields)):
            print(_red("  Invalid field number"))
            return
        field = fields[idx]
        current = self._ctrl.get_value(namespace, field.key)
        if current == field.default:
            print(
                _dim(f"  {field.label} is already at default"),
            )
            return
        error = self._ctrl.reset_field(namespace, field.key)
        if error:
            print(_red(f"  Error: {error}"))
        else:
            default_disp = format_field_value(field, field.default)
            print(
                _yellow(
                    f"  Buffered reset: {field.label} → {default_disp}"
                ),
            )

    # ── Main loop ───────────────────────────────────────────────

    def run(self) -> int:
        """Run the interactive settings menu.

        Returns:
            Exit code (0 = success).
        """
        try:
            while True:
                self._screen_home()
        except _ExitMenu:
            print(_dim("\n  Goodbye!"))
            return 0


class _ExitMenu(Exception):
    """Sentinel exception to break out of the menu loop."""


class _BackLevel(Exception):
    """Sentinel exception to go back one navigation level."""


# ── Public entry point ──────────────────────────────────────────────


def run_interactive_menu(settings_manager: SettingsManager) -> int:
    """Launch the interactive settings menu.

    Args:
        settings_manager: Initialized SettingsManager with schemas.

    Returns:
        Exit code (0 = success).
    """
    menu = InteractiveSettingsMenu(settings_manager)
    return menu.run()
