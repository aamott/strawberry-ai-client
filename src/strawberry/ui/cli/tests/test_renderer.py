"""Tests for CLI renderer behavior."""

from __future__ import annotations

import os

from strawberry.ui.cli.events import CLIEventType, ToolResultEvent, VoiceStatusEvent
from strawberry.ui.cli.renderer import CLIRenderer


def test_tool_result_toggle_renders_preview_and_full(capsys) -> None:
    """Toggle tool result output between preview and full content."""
    renderer = CLIRenderer(shortcuts_text="/h Help")
    event = ToolResultEvent(
        type=CLIEventType.TOOL_RESULT,
        tool_name="read",
        preview="line1 ... +1 lines",
        content="line1\nline2",
    )

    renderer.render_tool_result(event, collapsed=True)
    collapsed_output = capsys.readouterr().out
    assert "Shift+Tab to expand" in collapsed_output
    assert "line1" in collapsed_output

    renderer.toggle_latest_tool_result()
    expanded_output = capsys.readouterr().out
    assert "Shift+Tab to collapse" in expanded_output
    assert "line2" in expanded_output


def test_status_bar_renders_left_and_right(capsys, monkeypatch) -> None:
    """Render the status bar with shortcuts and voice status."""
    renderer = CLIRenderer(shortcuts_text="Alt+V Voice")
    terminal_size = os.terminal_size((40, 20))
    monkeypatch.setattr(
        "strawberry.ui.cli.renderer.shutil.get_terminal_size",
        lambda _default: terminal_size,
    )

    renderer.render_voice_status(
        VoiceStatusEvent(type=CLIEventType.VOICE_STATUS, status="waiting")
    )
    output = capsys.readouterr().out
    assert "Alt+V Voice" in output
    assert "Waiting" in output
