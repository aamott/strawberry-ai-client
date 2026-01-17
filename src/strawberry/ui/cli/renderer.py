"""Rendering helpers for the CLI UI."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Dict, Optional

from .events import ErrorEvent, MessageEvent, ToolCallEvent, ToolResultEvent, VoiceStatusEvent


@dataclass
class CLIColors:
    """ANSI color codes for CLI output."""

    reset: str = "\033[0m"
    bold: str = "\033[1m"
    dim: str = "\033[2m"
    blue: str = "\033[34m"
    cyan: str = "\033[36m"
    green: str = "\033[32m"
    yellow: str = "\033[33m"
    red: str = "\033[31m"
    gray: str = "\033[90m"


class CLIRenderer:
    """Render CLI events and the bottom status bar.

    Args:
        shortcuts_text: Shortcut help string to show on the left of the status bar.
        colors: Optional ANSI color palette override.
    """

    def __init__(self, shortcuts_text: str, colors: Optional[CLIColors] = None) -> None:
        self._colors = colors or CLIColors()
        self._shortcuts_text = shortcuts_text
        self._voice_status = "waiting"
        self._tool_results: list[ToolResultEvent] = []
        self._tool_collapsed: Dict[int, bool] = {}

    def render_message(self, event: MessageEvent) -> None:
        """Render a chat message to the terminal."""
        role = event.role.lower()
        if role == "user":
            prefix = f"{self._colors.blue}>{self._colors.reset}"
        elif role == "assistant":
            prefix = f"{self._colors.cyan}*{self._colors.reset}"
        else:
            prefix = f"{self._colors.yellow}!{self._colors.reset}"
        print(f"{prefix} {event.content}")

    def render_tool_call(self, event: ToolCallEvent) -> None:
        """Render a tool call summary."""
        preview = event.preview or ""
        name = event.tool_name or "Tool"
        print(
            f"{self._colors.green}* {name}{self._colors.reset}"
            f"({self._colors.dim}{preview}{self._colors.reset})"
        )

    def render_tool_result(self, event: ToolResultEvent, *, collapsed: bool = True) -> None:
        """Render a tool result preview or full output."""
        index = len(self._tool_results)
        self._tool_results.append(event)
        self._tool_collapsed[index] = collapsed
        self._render_tool_result_index(index)

    def toggle_latest_tool_result(self) -> bool:
        """Toggle the latest tool result between collapsed and expanded.

        Returns:
            True if a tool result was toggled, False if none exist.
        """
        if not self._tool_results:
            return False
        index = len(self._tool_results) - 1
        self._tool_collapsed[index] = not self._tool_collapsed.get(index, True)
        self._render_tool_result_index(index)
        return True

    def show_last_tool_result(self) -> bool:
        """Render the latest tool result in expanded form.

        Returns:
            True if a tool result was rendered, False otherwise.
        """
        if not self._tool_results:
            return False
        index = len(self._tool_results) - 1
        self._tool_collapsed[index] = False
        self._render_tool_result_index(index)
        return True

    def render_voice_status(self, event: VoiceStatusEvent) -> None:
        """Update the voice status and re-render the status bar."""
        self._voice_status = event.status
        self.render_status_bar()

    def render_error(self, event: ErrorEvent) -> None:
        """Render an error event."""
        print(f"{self._colors.red}* Error: {event.message}{self._colors.reset}")

    def render_status_bar(self) -> None:
        """Render the bottom status bar with shortcuts (left) and status (right)."""
        terminal_width = shutil.get_terminal_size((80, 20)).columns
        status_text, status_color = self._status_label()
        left_text = self._shortcuts_text
        right_text = f"{status_color}o {status_text}{self._colors.reset}"

        padding = terminal_width - len(self._strip_ansi(left_text)) - len(
            self._strip_ansi(right_text)
        )
        padding = max(padding, 1)
        print(f"{left_text}{' ' * padding}{right_text}")

    def _render_tool_result_index(self, index: int) -> None:
        """Render a stored tool result by index."""
        event = self._tool_results[index]
        collapsed = self._tool_collapsed.get(index, True)
        hint = "(Shift+Tab to expand)" if collapsed else "(Shift+Tab to collapse)"
        preview = event.preview or self._preview_from_content(event.content)

        if collapsed:
            print(f"{self._colors.dim}|  {preview} {hint}{self._colors.reset}")
            return

        print(f"{self._colors.dim}|  {hint}{self._colors.reset}")
        for line in (event.content or "").splitlines() or ["(empty)"]:
            print(f"{self._colors.dim}   {line}{self._colors.reset}")

    def _preview_from_content(self, content: str) -> str:
        """Build a preview line from full content."""
        if not content:
            return "(empty)"
        first_line = content.splitlines()[0]
        if len(first_line) > 60:
            return f"{first_line[:60]}..."
        return first_line

    def _status_label(self) -> tuple[str, str]:
        """Map voice status to display label and color."""
        status_map = {
            "waiting": ("Waiting...", self._colors.blue),
            "listening": ("Listening", self._colors.green),
            "processing": ("Processing...", self._colors.yellow),
            "muted": ("Muted", self._colors.gray),
        }
        return status_map.get(self._voice_status, (self._voice_status, self._colors.gray))

    def _strip_ansi(self, text: str) -> str:
        """Strip ANSI escape sequences for width calculations."""
        result = []
        skip = False
        for char in text:
            if char == "\033":
                skip = True
            if not skip:
                result.append(char)
            if skip and char == "m":
                skip = False
        return "".join(result)
