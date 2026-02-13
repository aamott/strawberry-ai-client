"""Interactive CLI mode for the test CLI.

Provides a full-featured REPL with slash commands, voice support,
and real-time event notifications. Uses SpokeCore's EventBus directly
for hub/voice/mode notifications — no custom pub/sub needed.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ...spoke_core.event_bus import Subscription

logger = logging.getLogger(__name__)

# ── ANSI helpers ──────────────────────────────────────────────────────

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"
GRAY = "\033[90m"


def _styled(text: str, *styles: str) -> str:
    """Apply ANSI styles to text."""
    if not styles:
        return text
    return "".join(styles) + text + RESET


# ── InteractiveCLI ────────────────────────────────────────────────────


class InteractiveCLI:
    """Interactive REPL with slash commands, voice, and event notifications.

    Uses SpokeCore directly and subscribes to its EventBus for
    connection/mode/error notifications. System messages are printed
    in dim gray; the ``>`` prompt is re-shown after each notification.

    Args:
        offline: If True, skip hub connection.
        timeout: Per-message timeout in seconds.
        config_dir: Path to config directory (default: project config/).
    """

    def __init__(
        self,
        offline: bool = False,
        timeout: int = 120,
        config_dir: Optional[Path] = None,
        verbose: bool = False,
    ) -> None:
        self._offline = offline
        self._timeout = float(timeout)
        self._config_dir = config_dir
        self._verbose = verbose

        # Populated in run()
        self._core: Any = None
        self._settings_manager: Any = None
        self._session_id: Optional[str] = None
        self._subscription: Optional[Subscription] = None
        self._running = False

        # Voice state
        self._voice_enabled = False
        self._voice_core: Any = None
        self._wakeword: str = ""

        # Track whether we're waiting for a response (suppress extra prompts)
        self._busy = False

        # Last tool result for /last command
        self._last_tool_result: Optional[str] = None

    # ── Prompt ────────────────────────────────────────────────────────

    def _get_prompt(self) -> str:
        """Build the prompt string based on current state."""
        if self._voice_enabled and self._wakeword:
            return _styled(f"{self._wakeword} > ", GREEN)
        return _styled("> ", BLUE)

    def _show_prompt(self) -> None:
        """Write the prompt to stdout without a newline."""
        sys.stdout.write(self._get_prompt())
        sys.stdout.flush()

    # ── Output helpers ────────────────────────────────────────────────

    def _print_system(self, message: str) -> None:
        """Print a system notification in gray, then re-show the prompt."""
        sys.stdout.write(f"\r{_styled(message, GRAY)}\n")
        sys.stdout.flush()
        if not self._busy:
            self._show_prompt()

    def _print_error(self, message: str) -> None:
        """Print an error message in red."""
        sys.stdout.write(f"\r{_styled(message, RED)}\n")
        sys.stdout.flush()
        if not self._busy:
            self._show_prompt()

    def _print_tool_call(self, name: str, args: dict) -> None:
        """Print a tool call notification."""
        if name == "python_exec" and "code" in args:
            code = str(args.get("code") or "")
            header = _styled(f"  * {name}", CYAN) + _styled("(code=)", DIM)
            sys.stdout.write(f"\r{header}\n")
            for line in code.splitlines():
                sys.stdout.write(f"  {_styled(line, DIM)}\n")
        elif self._verbose:
            # Verbose: show all args, no truncation
            import json as _json

            args_str = _json.dumps(args, indent=2, default=str)
            header = _styled(f"  * {name}", CYAN)
            sys.stdout.write(f"\r{header}\n")
            for line in args_str.splitlines():
                sys.stdout.write(f"  {_styled(line, DIM)}\n")
        else:
            preview = ", ".join(
                f"{k}={v!r}" for k, v in list(args.items())[:3]
            )
            if len(preview) > 60:
                preview = preview[:57] + "..."
            header = _styled(f"  * {name}", CYAN) + _styled(f"({preview})", DIM)
            sys.stdout.write(f"\r{header}\n")
        sys.stdout.flush()

    def _print_tool_result(
        self, name: str, success: bool, result: Optional[str], error: Optional[str],
    ) -> None:
        """Print a tool call result."""
        output = result if success else error

        if self._verbose:
            # Verbose: show full output, no truncation
            preview = output or ""
        else:
            preview = (output or "")[:80]
            if output and len(output) > 80:
                preview += "..."

        if success:
            status = _styled("OK", GREEN)
            text = _styled(preview, GREEN) if preview else ""
        else:
            status = _styled("ERR", RED)
            text = _styled(preview, RED) if preview else ""

        label = _styled(f"  * {name}", CYAN)
        sys.stdout.write(f"\r{label} [{status}] {text}\n")
        sys.stdout.flush()

    def _print_assistant(self, content: str) -> None:
        """Print an assistant response."""
        sys.stdout.write(f"\r\n{content}\n\n")
        sys.stdout.flush()

    # ── Main run loop ─────────────────────────────────────────────────

    async def run(self) -> int:
        """Start SpokeCore, subscribe to events, and run the input loop.

        Returns:
            Exit code (0 = success).
        """
        from ...shared.settings import SettingsManager
        from ...spoke_core import SpokeCore
        from ...utils.paths import get_project_root

        # Setup config
        if self._config_dir is None:
            self._config_dir = get_project_root() / "config"

        self._settings_manager = SettingsManager(
            config_dir=self._config_dir,
            env_filename="../.env",
        )
        self._core = SpokeCore(settings_manager=self._settings_manager)

        try:
            import time as _time

            # Per-skill load callback (verbose only)
            skill_cb = None
            if self._verbose:
                def _on_skill(name: str, source: str, ms: float) -> None:
                    t = f"{ms:.0f}ms" if ms < 1000 else f"{ms / 1000:.1f}s"
                    sys.stdout.write(
                        f"  {_styled(name, CYAN)}"
                        f" {_styled(f'({source}, {t})', DIM)}\n"
                    )
                    sys.stdout.flush()
                skill_cb = _on_skill

            t0 = _time.monotonic()
            await self._core.start(on_skill_loaded=skill_cb)
            startup_s = _time.monotonic() - t0

            # Create session
            session = self._core.new_session()
            self._session_id = session.id

            # Subscribe to SpokeCore events
            self._subscription = self._core.subscribe(self._handle_event)

            # Connect to hub unless offline
            if not self._offline:
                try:
                    await self._core.connect_hub()
                except Exception as e:
                    logger.warning("Hub connection failed: %s", e)

            self._running = True
            self._print_welcome(startup_s=startup_s)

            # Run input loop
            return await self._input_loop()

        except KeyboardInterrupt:
            self._print_system("Interrupted.")
            return 0
        except Exception as e:
            logger.exception("Interactive CLI error")
            self._print_error(f"Fatal error: {e}")
            return 1
        finally:
            await self._shutdown()

    def _print_welcome(self, startup_s: float = 0.0) -> None:
        """Print the welcome banner.

        Args:
            startup_s: Core startup duration in seconds.
        """
        online = self._core.is_online()
        mode = _styled("Online", GREEN) if online else _styled("Local", YELLOW)
        model = self._core.get_model_info()
        skill_count = len(self._core.get_skill_summaries())

        sys.stdout.write(f"\n{_styled('Strawberry CLI', CYAN, BOLD)}\n")
        sys.stdout.write(f"  Mode:   {mode}\n")
        sys.stdout.write(f"  Model:  {_styled(model, DIM)}\n")
        sys.stdout.write(
            f"  Skills: {_styled(str(skill_count), CYAN)}"
            f" {_styled(f'({startup_s:.1f}s)', DIM)}\n"
        )
        if self._verbose:
            sys.stdout.write(
                f"  {_styled('[verbose mode]', YELLOW)}\n"
            )
        sys.stdout.write(f"  {_styled('Type /help for commands', DIM)}\n\n")

        # Verbose: dump full system prompt
        if self._verbose:
            prompt = self._core.get_system_prompt()
            sys.stdout.write(
                f"{_styled('[system prompt]', CYAN)}\n{prompt}\n\n"
            )

        sys.stdout.flush()
        self._show_prompt()

    # ── Input loop ────────────────────────────────────────────────────

    async def _input_loop(self) -> int:
        """Read user input and dispatch commands or chat messages."""
        # Prefer aioconsole for non-blocking input; fall back to thread
        try:
            from aioconsole import ainput  # noqa: F401
            use_aioconsole = True
        except ImportError:
            use_aioconsole = False

        while self._running:
            try:
                if use_aioconsole:
                    from aioconsole import ainput
                    raw = await ainput("")
                else:
                    raw = await asyncio.to_thread(sys.stdin.readline)

                user_input = raw.strip()
                if not user_input:
                    self._show_prompt()
                    continue

                if user_input.startswith("/"):
                    await self._handle_command(user_input)
                else:
                    await self._send_message(user_input)

            except EOFError:
                break
            except KeyboardInterrupt:
                self._print_system("Interrupted.")
                break

        return 0

    # ── Chat ──────────────────────────────────────────────────────────

    async def _send_message(self, text: str) -> None:
        """Send a user message through SpokeCore and wait for response."""
        if not self._core or not self._session_id:
            return

        self._busy = True
        try:
            await asyncio.wait_for(
                self._core.send_message(self._session_id, text),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            self._print_error(f"Timed out after {self._timeout:.0f}s")
        except Exception as e:
            self._print_error(f"Error: {e}")
        finally:
            self._busy = False
            self._show_prompt()

    # ── Event handling ────────────────────────────────────────────────

    def _handle_event(self, event: Any) -> None:
        """Handle a SpokeCore event. Called by the EventBus subscription.

        This is the single callback that reacts to all core events —
        connection changes, mode changes, messages, tool calls, errors.
        """
        from ...spoke_core import (
            ConnectionChanged,
            CoreError,
            MessageAdded,
            ModeChanged,
            ToolCallResult,
            ToolCallStarted,
        )

        if isinstance(event, ConnectionChanged):
            if event.connected:
                self._print_system(f"Connected to Hub ({event.url or 'unknown'})")
            elif event.error:
                self._print_system(f"Hub: {event.error}")
            else:
                self._print_system("Disconnected from Hub")

        elif isinstance(event, ModeChanged):
            self._print_system(event.message)

        elif isinstance(event, ToolCallStarted):
            self._print_tool_call(event.tool_name, event.arguments)

        elif isinstance(event, ToolCallResult):
            self._print_tool_result(
                event.tool_name, event.success, event.result, event.error,
            )
            # Stash for /last
            self._last_tool_result = event.result if event.success else event.error

        elif isinstance(event, MessageAdded):
            if event.role == "assistant":
                self._print_assistant(event.content)
                # TTS if voice is active
                if self._voice_enabled and self._voice_core:
                    self._voice_core.speak(event.content)

        elif isinstance(event, CoreError):
            self._print_error(f"Error: {event.error}")

    # ── Slash commands ────────────────────────────────────────────────

    async def _handle_command(self, raw: str) -> None:
        """Dispatch a slash command.

        Args:
            raw: Full input string starting with '/'.
        """
        parts = raw.strip().split()
        cmd = parts[0].lower()

        if cmd in ("/help", "/h"):
            self._cmd_help()
        elif cmd in ("/quit", "/q", "/exit"):
            self._print_system("Goodbye!")
            self._running = False
            return
        elif cmd == "/voice":
            await self._toggle_voice()
        elif cmd == "/settings":
            self._cmd_settings()
        elif cmd == "/status":
            self._cmd_status()
        elif cmd == "/connect":
            await self._cmd_connect()
        elif cmd == "/clear":
            self._cmd_clear()
        elif cmd == "/last":
            self._cmd_last()
        else:
            self._print_error(f"Unknown command: {cmd}")
            self._print_system("Type /help for commands")
            return

        if self._running:
            self._show_prompt()

    def _cmd_help(self) -> None:
        """Print available commands."""
        lines = [
            "",
            _styled("Commands:", CYAN, BOLD),
            f"  {_styled('/help, /h', CYAN):30s} Show this help",
            f"  {_styled('/quit, /q', CYAN):30s} Quit",
            f"  {_styled('/voice', CYAN):30s} Toggle voice mode",
            f"  {_styled('/settings', CYAN):30s} Open settings menu",
            f"  {_styled('/status', CYAN):30s} Show status",
            f"  {_styled('/connect', CYAN):30s} Reconnect to Hub",
            f"  {_styled('/clear', CYAN):30s} Clear conversation",
            f"  {_styled('/last', CYAN):30s} Show last tool output",
            "",
        ]
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()

    def _cmd_status(self) -> None:
        """Print current status."""
        online = self._core.is_online() if self._core else False
        model = self._core.get_model_info() if self._core else "unknown"
        voice = "ON" if self._voice_enabled else "OFF"
        mode = _styled("Online (Hub)", GREEN) if online else _styled("Local", YELLOW)
        sys.stdout.write(
            f"\n  Mode:  {mode}\n"
            f"  Model: {_styled(model, DIM)}\n"
            f"  Voice: {_styled(voice, GREEN if self._voice_enabled else DIM)}\n\n"
        )
        sys.stdout.flush()

    async def _cmd_connect(self) -> None:
        """Attempt to connect (or reconnect) to the Hub."""
        self._print_system("Connecting to Hub...")
        try:
            connected = await self._core.connect_hub()
            if connected:
                self._print_system("Connected!")
            else:
                self._print_system("Connection failed.")
        except Exception as e:
            self._print_error(f"Connection error: {e}")

    def _cmd_clear(self) -> None:
        """Clear conversation history."""
        if self._session_id and self._core:
            session = self._core.get_session(self._session_id)
            if session:
                session.clear()
        # Clear terminal
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
        self._print_welcome()

    def _cmd_last(self) -> None:
        """Show the full last tool result."""
        if self._last_tool_result:
            sys.stdout.write(f"\n{self._last_tool_result}\n\n")
            sys.stdout.flush()
        else:
            self._print_system("No tool output yet.")

    def _cmd_settings(self) -> None:
        """Open the interactive settings menu."""
        if not self._settings_manager:
            self._print_error("Settings not available.")
            return

        from .settings_menu import run_interactive_menu

        run_interactive_menu(self._settings_manager)

    # ── Voice ─────────────────────────────────────────────────────────

    async def _toggle_voice(self) -> None:
        """Toggle voice mode on/off."""
        if self._voice_enabled:
            await self._stop_voice()
            self._print_system("Voice mode disabled.")
        else:
            await self._start_voice()

    async def _start_voice(self) -> None:
        """Start voice mode with wakeword detection."""
        try:
            from ...voice import VoiceConfig, VoiceCore

            voice_config = VoiceConfig()
            self._voice_core = VoiceCore(
                config=voice_config,
                response_handler=self._voice_response_handler,
                settings_manager=self._settings_manager,
            )
            self._voice_core.add_listener(self._on_voice_event)

            if await self._voice_core.start():
                self._voice_enabled = True
                # Grab the first wakeword for the prompt
                if voice_config.wake_words:
                    self._wakeword = voice_config.wake_words[0]
                self._print_system(
                    "Voice mode enabled. "
                    f"Say '{self._wakeword or 'wake word'}' to activate."
                )
            else:
                self._print_error("Failed to start voice mode.")
                self._voice_core = None

        except ImportError as e:
            self._print_error(f"Voice dependencies not available: {e}")
        except Exception as e:
            logger.exception("Voice start error")
            self._print_error(f"Voice error: {e}")

    async def _stop_voice(self) -> None:
        """Stop voice mode."""
        if self._voice_core:
            await self._voice_core.stop()
            self._voice_core = None
        self._voice_enabled = False
        self._wakeword = ""

    def _on_voice_event(self, event: Any) -> None:
        """Handle voice events — print as system notifications.

        Args:
            event: Voice event from VoiceCore.
        """
        from ...voice import (
            VoiceError,
            VoiceListening,
            VoiceNoSpeechDetected,
            VoiceSpeaking,
            VoiceState,
            VoiceStateChanged,
            VoiceTranscription,
            VoiceWakeWordDetected,
        )

        if isinstance(event, VoiceWakeWordDetected):
            self._print_system(f"Wake word detected: '{event.keyword}'")

        elif isinstance(event, VoiceListening):
            self._print_system("Listening...")

        elif isinstance(event, VoiceNoSpeechDetected):
            self._print_system("No speech detected.")

        elif isinstance(event, VoiceTranscription):
            if event.is_final and event.text:
                sys.stdout.write(
                    f"\r{_styled('You (voice):', GREEN)} {event.text}\n"
                )
                sys.stdout.flush()
                # Send transcription to SpokeCore
                if self._session_id:
                    return self._send_voice_transcription(event.text)

        elif isinstance(event, VoiceSpeaking):
            self._print_system(f"Speaking: {event.text[:60]}...")

        elif isinstance(event, VoiceError):
            self._print_error(f"Voice error: {event.error}")

        elif isinstance(event, VoiceStateChanged):
            if event.new_state == VoiceState.ERROR:
                self._print_error("Voice entered error state; disabling.")
                return self._stop_voice()

        return None

    async def _send_voice_transcription(self, text: str) -> None:
        """Send a voice transcription through SpokeCore."""
        if self._session_id:
            self._busy = True
            try:
                await self._core.send_message(self._session_id, text)
            except Exception as e:
                self._print_error(f"Error: {e}")
            finally:
                self._busy = False
                self._show_prompt()

    def _voice_response_handler(self, text: str) -> str:
        """Sync callback from VoiceCore when STT completes.

        We handle transcriptions via events instead, so return empty.
        """
        return ""

    # ── Shutdown ──────────────────────────────────────────────────────

    async def _shutdown(self) -> None:
        """Clean up all resources."""
        if self._voice_enabled:
            await self._stop_voice()

        if self._subscription:
            self._subscription.cancel()
            self._subscription = None

        if self._core:
            await self._core.stop()
            self._core = None
