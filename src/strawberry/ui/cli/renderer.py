"""ANSI terminal output formatting for CLI UI."""

import sys
from typing import Optional


# ANSI color codes
class Colors:
    """ANSI color codes for terminal output."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Foreground colors
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"

    # Background colors
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"


def styled(text: str, *styles: str) -> str:
    """Apply ANSI styles to text.

    Args:
        text: Text to style
        *styles: ANSI style codes to apply

    Returns:
        Styled text string
    """
    if not styles:
        return text
    return "".join(styles) + text + Colors.RESET


def print_system(message: str) -> None:
    """Print a system message in gray."""
    print(styled(f"[system] {message}", Colors.GRAY), flush=True)


def print_error(message: str) -> None:
    """Print an error message in red."""
    print(styled(f"[error] {message}", Colors.RED), flush=True)


def print_user(message: str) -> None:
    """Print user message (for echo/confirmation)."""
    # User messages are typically not echoed, but available if needed
    print(styled(f"> {message}", Colors.BLUE), flush=True)


def print_assistant(message: str) -> None:
    """Print assistant response."""
    print(f"\n{message}\n", flush=True)


def print_tool_call(
    tool_name: str,
    args_preview: str,
    result_preview: Optional[str] = None,
    success: bool = True,
) -> None:
    """Print a tool call summary line.

    Format: * tool_name(arg_preview...) → <result_preview>

    Args:
        tool_name: Name of the tool
        args_preview: Preview of arguments (max 40 chars)
        result_preview: Preview of result (max 40 chars)
        success: Whether the tool call succeeded
    """
    if tool_name == "python_exec" and "\n" in args_preview:
        call_part = styled(f"* CALL {tool_name}", Colors.CYAN)
        args_part = styled("(code=)", Colors.DIM)
        if result_preview is not None:
            arrow = styled(" → ", Colors.GRAY)
            if success:
                result_part = styled(result_preview[:40] + "...", Colors.GREEN)
            else:
                result_part = styled(result_preview[:40] + "...", Colors.RED)
            print(f"{call_part}{args_part}{arrow}{result_part}", flush=True)
            return

        print(f"{call_part}{args_part} ...", flush=True)
        for line in args_preview.splitlines():
            print(styled(f"  {line}", Colors.DIM), flush=True)
        return

    # Truncate previews
    if len(args_preview) > 40:
        args_preview = args_preview[:37] + "..."
    if result_preview and len(result_preview) > 40:
        result_preview = result_preview[:37] + "..."

    # Build the line
    call_part = styled(f"* CALL {tool_name}", Colors.CYAN)
    args_part = styled(f"({args_preview})", Colors.DIM)

    if result_preview is not None:
        arrow = styled(" → ", Colors.GRAY)
        if success:
            result_part = styled(result_preview, Colors.GREEN)
        else:
            result_part = styled(result_preview, Colors.RED)
        print(f"{call_part}{args_part}{arrow}{result_part}", flush=True)
    else:
        # Tool started, no result yet
        print(f"{call_part}{args_part} ...", flush=True)


def print_tool_result(
    tool_name: str,
    success: bool,
    result: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Print tool result on a new line.

    Args:
        tool_name: Name of the tool
        success: Whether the tool call succeeded
        result: Result text if success
        error: Error text if failed
    """
    # Print tool results on a new line to avoid overwriting prompt/input lines
    sys.stdout.write("\n")
    sys.stdout.flush()

    output = result if success else error
    preview = output[:40] + "..." if output and len(output) > 40 else (output or "")

    if success:
        status = styled("✓", Colors.GREEN)
        result_text = styled(preview, Colors.GREEN) if preview else ""
    else:
        status = styled("✗", Colors.RED)
        result_text = styled(preview, Colors.RED) if preview else ""

    tool_part = styled(f"* RESULT {tool_name}", Colors.CYAN)
    print(f"{tool_part} {status} {result_text}", flush=True)


def print_prompt(voice_active: bool = False) -> str:
    """Print the input prompt and return it.

    Args:
        voice_active: If True, prompt is green; otherwise blue

    Returns:
        The prompt string
    """
    color = Colors.GREEN if voice_active else Colors.BLUE
    return styled("> ", color)


def print_status(text: str) -> None:
    """Print a status line (model info, connection status, etc.)."""
    print(styled(f"[{text}]", Colors.DIM), flush=True)


def print_help() -> None:
    """Print help message with available commands."""
    help_text = """
Available commands:
  /help     - Show this help message
  /quit, /q - Quit the CLI
  /clear    - Clear conversation history
  /last     - Show full output of last tool call
  /voice    - Toggle voice mode (green prompt when active)
  /connect  - Connect to Hub
  /status   - Show connection status
  /settings - Open settings menu
"""
    print(styled(help_text, Colors.CYAN), flush=True)


def print_welcome(model: str, online: bool) -> None:
    """Print welcome message.

    Args:
        model: Current model name
        online: Whether connected to Hub
    """
    mode = styled("Online", Colors.GREEN) if online else styled("Local", Colors.YELLOW)
    border = Colors.CYAN
    print(styled("\n╭─────────────────────────────────────╮", border), flush=True)
    print(
        styled("│", border)
        + "   Strawberry CLI                    "
        + styled("│", border),
        flush=True,
    )
    print(
        styled("│", border)
        + f"   Mode: {mode}                        "
        + styled("│", border),
        flush=True,
    )
    print(
        styled("│", border)
        + f"   Model: {model[:20]:<20}     "
        + styled("│", border),
        flush=True,
    )
    print(styled("╰─────────────────────────────────────╯", border), flush=True)
    print(styled("Type /help for commands\n", Colors.DIM), flush=True)


def clear_screen() -> None:
    """Clear the terminal screen."""
    print("\033[2J\033[H", end="", flush=True)


# =============================================================================
# String-returning functions (for testing and composability)
# =============================================================================


def status_bar(state: str, width: int = 80) -> str:
    """Generate a status bar string.

    Args:
        state: Voice state (OFF, LISTENING, IDLE, SPEAKING)
        width: Terminal width

    Returns:
        Formatted status bar string
    """
    state_labels = {
        "OFF": "Voice: Off",
        "LISTENING": "Listening...",
        "IDLE": "Waiting for wake word",
        "SPEAKING": "Speaking...",
    }
    state_text = state_labels.get(state.upper(), state)
    commands = "/voice /help /quit"
    padding = width - len(state_text) - len(commands) - 4
    return f"[{state_text}]{' ' * max(1, padding)}[{commands}]"


def user_message(text: str) -> str:
    """Format a user message.

    Args:
        text: User message text

    Returns:
        Formatted user message string
    """
    return styled(f"> {text}", Colors.BLUE)


def assistant_message(text: str) -> str:
    """Format an assistant message.

    Args:
        text: Assistant message text

    Returns:
        Formatted assistant message string
    """
    return text


def tool_call_started(tool_name: str, args_preview: str) -> str:
    """Format a tool call start message.

    Args:
        tool_name: Name of the tool
        args_preview: Preview of arguments

    Returns:
        Formatted tool call string
    """
    return styled(f"* {tool_name}", Colors.CYAN) + styled(f"({args_preview})", Colors.DIM)


def tool_call_result(success: bool, output: str) -> str:
    """Format a tool call result.

    Args:
        success: Whether the call succeeded
        output: Result or error text

    Returns:
        Formatted result string
    """
    if success:
        return styled(f"✓ {output}", Colors.GREEN)
    else:
        return styled(f"Error: {output}", Colors.RED)
