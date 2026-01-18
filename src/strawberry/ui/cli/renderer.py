"""ANSI terminal rendering for CLI UI."""

import os
import re

# ANSI codes
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
BLUE = "\033[34m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
GRAY = "\033[90m"


def get_width() -> int:
    """Get terminal width, default 80."""
    try:
        return min(os.get_terminal_size().columns, 120)
    except OSError:
        return 80


def separator() -> str:
    """Return a dim separator line."""
    return f"{DIM}{'─' * get_width()}{RESET}"


def header(app_name: str, status: str, model: str, cwd: str) -> str:
    """Render the header line."""
    return f"{BOLD}{app_name}{RESET} | {status} | {DIM}{model} | {cwd}{RESET}"


def user_prompt() -> str:
    """Return the user input prompt."""
    return f"{BOLD}{BLUE}❯{RESET} "


def user_message(text: str) -> str:
    """Render a user message."""
    return f"{BOLD}> {text}{RESET}"


def assistant_message(text: str) -> str:
    """Render an assistant message."""
    # Simple markdown: **bold**
    text = re.sub(r"\*\*(.+?)\*\*", f"{BOLD}\\1{RESET}{CYAN}", text)
    return f"{CYAN}⏺ {text}{RESET}"


def tool_call_started(name: str, args_preview: str) -> str:
    """Render a tool call start."""
    return f"{GREEN}⏺ {name}{RESET}({DIM}{args_preview}{RESET})"


def tool_call_result(success: bool, result: str) -> str:
    """Render a tool call result."""
    if success:
        # Truncate long results
        lines = result.split("\n")
        preview = lines[0][:60] if lines else ""
        if len(lines) > 1:
            preview += f" ... +{len(lines) - 1} lines"
        elif len(lines[0]) > 60:
            preview += "..."
        return f"  {DIM}⎿  {preview}{RESET}"
    else:
        return f"  {RED}⎿  Error: {result[:60]}{RESET}"


def error_message(text: str) -> str:
    """Render an error."""
    return f"{RED}⏺ Error: {text}{RESET}"


def info_message(text: str) -> str:
    """Render an info message."""
    return f"{GREEN}⏺ {text}{RESET}"


def help_text() -> str:
    """Return help text."""
    return f"""
{BOLD}Commands:{RESET}
  {DIM}/clear{RESET}  Clear conversation
  {DIM}/voice{RESET}  Toggle voice mode
  {DIM}/help{RESET}   Show this help
  {DIM}/quit{RESET}   Exit (or /q)
"""


def status_bar(voice_state: str, width: int) -> str:
    """Render the bottom status bar with voice state.

    Args:
        voice_state: Current voice state (OFF, STOPPED, IDLE, LISTENING, PROCESSING, SPEAKING)
        width: Terminal width

    Returns:
        Formatted status bar string
    """
    # Voice state indicator
    if voice_state in ("OFF", "STOPPED"):
        voice_indicator = f"{GRAY}○ Off{RESET}"
    elif voice_state == "IDLE":
        voice_indicator = f"{BLUE}● Waiting{RESET}"
    elif voice_state == "LISTENING":
        voice_indicator = f"{GREEN}● Listening{RESET}"
    elif voice_state in ("PROCESSING", "SPEAKING"):
        voice_indicator = f"{YELLOW}● Processing{RESET}"
    else:
        voice_indicator = f"{GRAY}○ {voice_state}{RESET}"

    # Left side: commands hint
    left = f"{DIM}/voice | /help{RESET}"

    # Right side: voice indicator
    right = voice_indicator

    # Calculate padding (accounting for ANSI codes)
    # Visible chars only for left and right
    left_visible = "/voice | /help"
    right_visible_map = {
        "OFF": "○ Off",
        "STOPPED": "○ Off",
        "IDLE": "● Waiting",
        "LISTENING": "● Listening",
        "PROCESSING": "● Processing",
        "SPEAKING": "● Processing",
    }
    right_visible = right_visible_map.get(voice_state, f"○ {voice_state}")

    padding_len = width - len(left_visible) - len(right_visible) - 2
    padding = " " * max(0, padding_len)

    return f"{DIM}─{RESET} {left}{padding}{right} {DIM}─{RESET}"
