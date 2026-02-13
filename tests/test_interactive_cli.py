"""Tests for the InteractiveCLI module.

Tests the ANSI helpers, prompt generation, output formatting, command
dispatch, and event handling — all without needing a live LLM or Hub.
"""

from __future__ import annotations

from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from strawberry.ui.test_cli.interactive import (
    BLUE,
    GRAY,
    GREEN,
    RED,
    RESET,
    InteractiveCLI,
    _styled,
)

# ── ANSI helper tests ─────────────────────────────────────────────────


class TestStyled:
    """Tests for the _styled() ANSI helper."""

    def test_no_styles(self):
        assert _styled("hello") == "hello"

    def test_single_style(self):
        result = _styled("hello", RED)
        assert result.startswith(RED)
        assert result.endswith(RESET)
        assert "hello" in result

    def test_multiple_styles(self):
        from strawberry.ui.test_cli.interactive import BOLD

        result = _styled("hello", RED, BOLD)
        assert result.startswith(RED + BOLD)
        assert "hello" in result


# ── Prompt tests ──────────────────────────────────────────────────────


class TestPrompt:
    """Tests for prompt generation."""

    def test_default_prompt_is_blue(self):
        cli = InteractiveCLI()
        prompt = cli._get_prompt()
        assert BLUE in prompt
        assert "> " in prompt

    def test_voice_prompt_includes_wakeword(self):
        cli = InteractiveCLI()
        cli._voice_enabled = True
        cli._wakeword = "jarvis"
        prompt = cli._get_prompt()
        assert GREEN in prompt
        assert "jarvis > " in prompt

    def test_voice_prompt_without_wakeword_is_plain(self):
        """If voice is on but no wakeword, use the default prompt."""
        cli = InteractiveCLI()
        cli._voice_enabled = True
        cli._wakeword = ""
        prompt = cli._get_prompt()
        # Falls back to default blue prompt
        assert BLUE in prompt
        assert "> " in prompt


# ── Output helper tests ──────────────────────────────────────────────


class TestOutputHelpers:
    """Tests for _print_system, _print_error, etc."""

    def _capture(self, cli: InteractiveCLI, method_name: str, *args) -> str:
        """Call an output method and capture stdout."""
        buf = StringIO()
        with patch("sys.stdout", buf):
            getattr(cli, method_name)(*args)
        return buf.getvalue()

    def test_print_system_gray(self):
        cli = InteractiveCLI()
        cli._busy = True  # Suppress prompt re-show
        output = self._capture(cli, "_print_system", "Hub connected")
        assert GRAY in output
        assert "Hub connected" in output

    def test_print_error_red(self):
        cli = InteractiveCLI()
        cli._busy = True
        output = self._capture(cli, "_print_error", "Something broke")
        assert RED in output
        assert "Something broke" in output

    def test_print_system_reshows_prompt_when_not_busy(self):
        cli = InteractiveCLI()
        cli._busy = False
        output = self._capture(cli, "_print_system", "test")
        # Should contain both the message and the prompt
        assert "test" in output
        assert "> " in output

    def test_print_assistant(self):
        cli = InteractiveCLI()
        output = self._capture(cli, "_print_assistant", "Hello there!")
        assert "Hello there!" in output

    def test_print_tool_call_regular(self):
        cli = InteractiveCLI()
        output = self._capture(
            cli, "_print_tool_call", "search_skills", {"query": "weather"},
        )
        assert "search_skills" in output
        assert "weather" in output

    def test_print_tool_call_python_exec(self):
        cli = InteractiveCLI()
        output = self._capture(
            cli,
            "_print_tool_call",
            "python_exec",
            {"code": "print('hello')\nprint('world')"},
        )
        assert "python_exec" in output
        assert "hello" in output
        assert "world" in output

    def test_print_tool_result_success(self):
        cli = InteractiveCLI()
        output = self._capture(
            cli, "_print_tool_result", "search_skills", True, "Found 3", None,
        )
        assert "OK" in output
        assert "Found 3" in output

    def test_print_tool_result_failure(self):
        cli = InteractiveCLI()
        output = self._capture(
            cli, "_print_tool_result", "python_exec", False, None, "NameError",
        )
        assert "ERR" in output
        assert "NameError" in output


# ── Command dispatch tests ────────────────────────────────────────────


class TestCommands:
    """Tests for slash command dispatch."""

    @pytest.mark.asyncio
    async def test_quit_stops_loop(self):
        cli = InteractiveCLI()
        cli._running = True
        cli._core = MagicMock()
        with patch("sys.stdout", StringIO()):
            await cli._handle_command("/quit")
        assert cli._running is False

    @pytest.mark.asyncio
    async def test_q_alias(self):
        cli = InteractiveCLI()
        cli._running = True
        cli._core = MagicMock()
        with patch("sys.stdout", StringIO()):
            await cli._handle_command("/q")
        assert cli._running is False

    @pytest.mark.asyncio
    async def test_help_prints_commands(self):
        cli = InteractiveCLI()
        cli._running = True
        cli._core = MagicMock()
        buf = StringIO()
        with patch("sys.stdout", buf):
            await cli._handle_command("/help")
        output = buf.getvalue()
        assert "/voice" in output
        assert "/settings" in output
        assert "/status" in output

    @pytest.mark.asyncio
    async def test_status_shows_mode_and_model(self):
        cli = InteractiveCLI()
        cli._running = True
        cli._core = MagicMock()
        cli._core.is_online.return_value = False
        cli._core.get_model_info.return_value = "llama3.2:3b"
        buf = StringIO()
        with patch("sys.stdout", buf):
            await cli._handle_command("/status")
        output = buf.getvalue()
        assert "Local" in output
        assert "llama3.2:3b" in output
        assert "OFF" in output

    @pytest.mark.asyncio
    async def test_last_shows_no_output_message(self):
        cli = InteractiveCLI()
        cli._running = True
        cli._core = MagicMock()
        cli._last_tool_result = None
        buf = StringIO()
        with patch("sys.stdout", buf):
            await cli._handle_command("/last")
        assert "No tool output" in buf.getvalue()

    @pytest.mark.asyncio
    async def test_last_shows_stored_result(self):
        cli = InteractiveCLI()
        cli._running = True
        cli._core = MagicMock()
        cli._last_tool_result = "42"
        buf = StringIO()
        with patch("sys.stdout", buf):
            await cli._handle_command("/last")
        assert "42" in buf.getvalue()

    @pytest.mark.asyncio
    async def test_unknown_command(self):
        cli = InteractiveCLI()
        cli._running = True
        cli._core = MagicMock()
        buf = StringIO()
        with patch("sys.stdout", buf):
            await cli._handle_command("/foobar")
        output = buf.getvalue()
        assert "Unknown command" in output

    @pytest.mark.asyncio
    async def test_connect_delegates_to_core(self):
        cli = InteractiveCLI()
        cli._running = True
        cli._core = AsyncMock()
        cli._core.connect_hub = AsyncMock(return_value=True)
        buf = StringIO()
        with patch("sys.stdout", buf):
            await cli._handle_command("/connect")
        cli._core.connect_hub.assert_awaited_once()
        assert "Connected" in buf.getvalue()


# ── Event handling tests ──────────────────────────────────────────────


class TestEventHandling:
    """Tests for _handle_event callback."""

    def _make_cli(self) -> tuple[InteractiveCLI, StringIO]:
        cli = InteractiveCLI()
        cli._busy = True  # Suppress prompt re-show
        buf = StringIO()
        return cli, buf

    def test_connection_changed_connected(self):
        from strawberry.spoke_core import ConnectionChanged

        cli, buf = self._make_cli()
        event = ConnectionChanged(connected=True, url="http://hub:8000")
        with patch("sys.stdout", buf):
            cli._handle_event(event)
        assert "Connected to Hub" in buf.getvalue()
        assert "hub:8000" in buf.getvalue()

    def test_connection_changed_disconnected(self):
        from strawberry.spoke_core import ConnectionChanged

        cli, buf = self._make_cli()
        event = ConnectionChanged(
            connected=False, error="Hub connection lost",
        )
        with patch("sys.stdout", buf):
            cli._handle_event(event)
        assert "Hub connection lost" in buf.getvalue()

    def test_mode_changed(self):
        from strawberry.spoke_core import ModeChanged

        cli, buf = self._make_cli()
        event = ModeChanged(online=False, message="Running in local mode.")
        with patch("sys.stdout", buf):
            cli._handle_event(event)
        assert "Running in local mode" in buf.getvalue()

    def test_tool_call_started(self):
        from strawberry.spoke_core import ToolCallStarted

        cli, buf = self._make_cli()
        event = ToolCallStarted(
            session_id="s1",
            tool_name="search_skills",
            arguments={"query": "weather"},
        )
        with patch("sys.stdout", buf):
            cli._handle_event(event)
        assert "search_skills" in buf.getvalue()

    def test_tool_call_result_stores_last(self):
        from strawberry.spoke_core import ToolCallResult

        cli, buf = self._make_cli()
        event = ToolCallResult(
            session_id="s1",
            tool_name="python_exec",
            success=True,
            result="42",
        )
        with patch("sys.stdout", buf):
            cli._handle_event(event)
        assert cli._last_tool_result == "42"

    def test_message_added_assistant(self):
        from strawberry.spoke_core import MessageAdded

        cli, buf = self._make_cli()
        event = MessageAdded(
            session_id="s1", role="assistant", content="Hello!",
        )
        with patch("sys.stdout", buf):
            cli._handle_event(event)
        assert "Hello!" in buf.getvalue()

    def test_core_error(self):
        from strawberry.spoke_core import CoreError

        cli, buf = self._make_cli()
        event = CoreError(error="Something went wrong")
        with patch("sys.stdout", buf):
            cli._handle_event(event)
        assert "Something went wrong" in buf.getvalue()


# ── Welcome banner test ───────────────────────────────────────────────


class TestWelcome:
    """Tests for the welcome banner."""

    def test_welcome_shows_local_mode(self):
        cli = InteractiveCLI()
        cli._core = MagicMock()
        cli._core.is_online.return_value = False
        cli._core.get_model_info.return_value = "test-model"
        buf = StringIO()
        with patch("sys.stdout", buf):
            cli._print_welcome()
        output = buf.getvalue()
        assert "Strawberry CLI" in output
        assert "Local" in output
        assert "test-model" in output

    def test_welcome_shows_online_mode(self):
        cli = InteractiveCLI()
        cli._core = MagicMock()
        cli._core.is_online.return_value = True
        cli._core.get_model_info.return_value = "gemini-2.0"
        buf = StringIO()
        with patch("sys.stdout", buf):
            cli._print_welcome()
        output = buf.getvalue()
        assert "Online" in output
        assert "gemini-2.0" in output
