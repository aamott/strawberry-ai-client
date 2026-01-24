"""CLI UI entrypoint for the Spoke.

Uses SpokeCore for chat and skill execution with async event handling.
"""

import asyncio
import atexit
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from . import renderer

# Configure logging to file instead of console.
LOG_DIR = Path(__file__).parent.parent.parent.parent.parent / ".cli-logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "cli.log"

ConnectionChanged = None
CoreError = None
CoreEvent = None
CoreReady = None
MessageAdded = None
ModeChanged = None
SpokeCore = None
ToolCallResult = None
ToolCallStarted = None

if TYPE_CHECKING:
    from ...spoke_core import (  # noqa: F401
        ConnectionChanged as ConnectionChangedType,
    )


def _configure_cli_logging() -> None:
    """Configure file logging and redirect stderr for CLI logs."""
    # Silence TensorZero Rust logs completely - must be set before gateway init
    os.environ["RUST_LOG"] = "off"
    stderr_log_handle = LOG_FILE.open("a", encoding="utf-8")
    os.dup2(stderr_log_handle.fileno(), sys.stderr.fileno())
    sys.stderr = stderr_log_handle
    atexit.register(stderr_log_handle.close)

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(LOG_FILE)],
    )


def _load_core_types() -> None:
    """Load SpokeCore symbols after CLI logging is configured."""
    global ConnectionChanged
    global CoreError
    global CoreEvent
    global CoreReady
    global MessageAdded
    global ModeChanged
    global SpokeCore
    global ToolCallResult
    global ToolCallStarted

    if SpokeCore is not None:
        return

    from ...spoke_core import (
        ConnectionChanged as _ConnectionChanged,
    )
    from ...spoke_core import (
        CoreError as _CoreError,
    )
    from ...spoke_core import (
        CoreEvent as _CoreEvent,
    )
    from ...spoke_core import (
        CoreReady as _CoreReady,
    )
    from ...spoke_core import (
        MessageAdded as _MessageAdded,
    )
    from ...spoke_core import (
        ModeChanged as _ModeChanged,
    )
    from ...spoke_core import (
        SpokeCore as _SpokeCore,
    )
    from ...spoke_core import (
        ToolCallResult as _ToolCallResult,
    )
    from ...spoke_core import (
        ToolCallStarted as _ToolCallStarted,
    )

    ConnectionChanged = _ConnectionChanged
    CoreError = _CoreError
    CoreEvent = _CoreEvent
    CoreReady = _CoreReady
    MessageAdded = _MessageAdded
    ModeChanged = _ModeChanged
    SpokeCore = _SpokeCore
    ToolCallResult = _ToolCallResult
    ToolCallStarted = _ToolCallStarted
logger = logging.getLogger(__name__)

# Suppress console output from libraries
for log_name in ["httpx", "httpcore", "asyncio", "urllib3"]:
    logging.getLogger(log_name).setLevel(logging.WARNING)


class CLIApp:
    """CLI application using SpokeCore with optional voice support."""

    def __init__(self) -> None:
        self._core = SpokeCore()
        self._session_id: Optional[str] = None
        self._running = False
        self._response_event = asyncio.Event()
        self._response_event.set()
        self._last_tool_result: Optional[str] = None
        self._pending_tool_calls: dict = {}

        # Voice support
        self._voice_enabled = False
        self._voice_core = None

    async def run(self) -> None:
        """Main run loop."""
        self._running = True

        try:
            # Start core
            await self._core.start()

            # Create session
            session = self._core.new_session()
            self._session_id = session.id

            # Try to connect to hub (blocking - wait for result before showing welcome)
            await self._try_connect_hub()

            # Print welcome (now shows correct online/offline status)
            renderer.print_welcome(
                model=self._core.get_model_info(),
                online=self._core.is_online(),
            )

            # Run input loop and event handler concurrently
            await asyncio.gather(
                self._input_loop(),
                self._event_loop(),
            )

        except KeyboardInterrupt:
            renderer.print_system("Interrupted")
        except Exception as e:
            logger.exception("CLI error")
            renderer.print_error(str(e))
        finally:
            self._running = False
            await self._stop_voice()
            await self._core.stop()

    async def _try_connect_hub(self) -> None:
        """Try to connect to hub before showing welcome."""
        try:
            await self._core.connect_hub()
            # Connection status will be shown in welcome message
        except Exception as e:
            logger.warning(f"Hub connection failed: {e}")
            # Will show as local mode in welcome

    async def _input_loop(self) -> None:
        """Handle user input."""
        try:
            # Try to use aioconsole for non-blocking input
            from aioconsole import ainput
            use_aioconsole = True
        except ImportError:
            use_aioconsole = False
            logger.warning("aioconsole not available, using blocking input")

        while self._running:
            try:
                if self._session_id:
                    session = self._core.get_session(self._session_id)
                    if session and session.busy:
                        await asyncio.sleep(0.05)
                        continue

                if not self._response_event.is_set():
                    await self._response_event.wait()

                # Green prompt when voice is active
                prompt = renderer.print_prompt(voice_active=self._voice_enabled)
                sys.stdout.write(prompt)
                sys.stdout.flush()

                if use_aioconsole:
                    user_input = await ainput("")
                else:
                    user_input = await asyncio.to_thread(sys.stdin.readline)

                user_input = user_input.strip()
                if not user_input:
                    continue

                if not sys.stdin.isatty():
                    sys.stdout.write(f"{user_input}\n")
                    sys.stdout.flush()

                # Handle slash commands
                if user_input.startswith("/"):
                    await self._handle_command(user_input)
                    continue

                # Send message to core
                if self._session_id:
                    self._response_event.clear()
                    await self._core.send_message(self._session_id, user_input)
                    await self._response_event.wait()

            except EOFError:
                break
            except asyncio.CancelledError:
                break

    async def _event_loop(self) -> None:
        """Handle events from SpokeCore."""
        try:
            async for event in self._core.events():
                if not self._running:
                    break
                await self._handle_event(event)
        except asyncio.CancelledError:
            pass

    async def _handle_event(self, event: CoreEvent) -> None:
        """Process a single event.

        Args:
            event: The event to handle
        """
        if isinstance(event, CoreReady):
            logger.info("Core ready")

        elif isinstance(event, CoreError):
            renderer.print_error(event.error)
            self._response_event.set()

        elif isinstance(event, MessageAdded):
            if event.role == "assistant":
                renderer.print_assistant(event.content)
                self._response_event.set()

                # Speak response if voice is enabled
                if self._voice_enabled and self._voice_core:
                    self._voice_core.speak(event.content)

            elif event.role == "system":
                renderer.print_system(event.content)
            # User messages are not echoed (user already sees their input)

        elif isinstance(event, ToolCallStarted):
            if event.tool_name == "python_exec" and "code" in event.arguments:
                renderer.print_tool_call(
                    event.tool_name,
                    str(event.arguments.get("code") or ""),
                )
            else:
                # Build args preview
                args_preview = ", ".join(
                    f"{k}={v!r}" for k, v in list(event.arguments.items())[:2]
                )
                renderer.print_tool_call(event.tool_name, args_preview)
            # Track for /last command
            self._pending_tool_calls[event.tool_name] = event.arguments

        elif isinstance(event, ToolCallResult):
            # Update the tool call line with result
            output = event.result if event.success else event.error
            renderer.print_tool_result(
                event.tool_name,
                event.success,
                event.result,
                event.error,
            )
            # Store for /last command
            self._last_tool_result = output
            self._pending_tool_calls.pop(event.tool_name, None)

        elif isinstance(event, ConnectionChanged):
            if event.connected:
                renderer.print_system(f"Connected to Hub ({event.url})")
            elif event.error:
                renderer.print_system(f"Hub: {event.error}")

        elif isinstance(event, ModeChanged):
            renderer.print_system(event.message)

    async def _handle_command(self, command: str) -> None:
        """Handle a slash command.

        Args:
            command: The command string starting with /
        """
        cmd = command.lower().split()[0]

        if cmd in ("/help", "/h"):
            renderer.print_help()

        elif cmd in ("/quit", "/q", "/exit"):
            renderer.print_system("Goodbye!")
            self._running = False

        elif cmd == "/clear":
            session = self._core.get_session(self._session_id) if self._session_id else None
            if session:
                session.clear()
            renderer.clear_screen()
            renderer.print_welcome(
                model=self._core.get_model_info(),
                online=self._core.is_online(),
            )
            renderer.print_system("Conversation cleared")

        elif cmd == "/last":
            if self._last_tool_result:
                print(f"\n{self._last_tool_result}\n")
            else:
                renderer.print_system("No tool output available")

        elif cmd == "/voice":
            await self._toggle_voice()

        elif cmd == "/connect":
            renderer.print_system("Connecting to Hub...")
            connected = await self._core.connect_hub()
            if connected:
                renderer.print_system("Connected!")
            else:
                renderer.print_system("Connection failed")

        elif cmd == "/status":
            online = self._core.is_online()
            model = self._core.get_model_info()
            voice = "ON" if self._voice_enabled else "OFF"
            status = "Online (Hub)" if online else "Local"
            renderer.print_status(f"Mode: {status} | Model: {model} | Voice: {voice}")

        else:
            renderer.print_error(f"Unknown command: {cmd}")
            renderer.print_system("Type /help for available commands")

    # -------------------------------------------------------------------------
    # Voice Support
    # -------------------------------------------------------------------------

    async def _toggle_voice(self) -> None:
        """Toggle voice mode on/off."""
        if self._voice_enabled:
            await self._stop_voice()
            renderer.print_system("Voice mode disabled")
        else:
            await self._start_voice()

    async def _start_voice(self) -> None:
        """Start voice mode."""
        try:
            # Lazy import to avoid loading voice deps if not needed
            from ...config import get_settings
            from ...voice import VoiceConfig, VoiceCore

            settings = get_settings()

            voice_config = VoiceConfig(
                wake_words=settings.wake_word.keywords or ["strawberry"],
                sensitivity=getattr(settings.wake_word, "sensitivity", 0.5),
                sample_rate=16000,
                stt_backend=settings.stt.backend,
                tts_backend=settings.tts.backend,
                vad_backend=settings.vad.backend,
                wake_backend=settings.wake_word.backend,
            )

            self._voice_core = VoiceCore(
                config=voice_config,
                response_handler=self._voice_response_handler,
            )

            # Subscribe to voice events
            self._voice_core.add_listener(self._on_voice_event)

            # Start voice core
            if await self._voice_core.start():
                self._voice_enabled = True
                wake_words = ", ".join(voice_config.wake_words)
                renderer.print_system(f"Voice mode enabled. Say '{wake_words}' to activate.")
            else:
                renderer.print_error("Failed to start voice mode")
                self._voice_core = None

        except ImportError as e:
            renderer.print_error(f"Voice dependencies not available: {e}")
        except Exception as e:
            logger.exception("Voice start error")
            renderer.print_error(f"Voice error: {e}")

    async def _stop_voice(self) -> None:
        """Stop voice mode."""
        if self._voice_core:
            await self._voice_core.stop()
            self._voice_core = None
        self._voice_enabled = False

    def _on_voice_event(self, event) -> None:
        """Handle voice events - print as system messages.

        Args:
            event: Voice event from VoiceCore
        """
        from ...voice import (
            VoiceError,
            VoiceListening,
            VoiceSpeaking,
            VoiceState,
            VoiceStateChanged,
            VoiceTranscription,
            VoiceWakeWordDetected,
        )

        if isinstance(event, VoiceWakeWordDetected):
            renderer.print_system(f"🎤 Wake word detected: '{event.keyword}'")

        elif isinstance(event, VoiceListening):
            renderer.print_system("🎤 Listening...")

        elif isinstance(event, VoiceTranscription):
            if event.is_final and event.text:
                # Print transcription as user-like message
                print(f"\n{renderer.styled('🗣️ You:', renderer.Colors.GREEN)} {event.text}")
                # Also send to SpokeCore if we have a session
                if self._session_id:
                    # Schedule async send
                    return self._send_voice_transcription(event.text)

        elif isinstance(event, VoiceSpeaking):
            renderer.print_system(f"🔊 Speaking: {event.text[:50]}...")

        elif isinstance(event, VoiceError):
            renderer.print_error(f"Voice error: {event.error}")

        elif isinstance(event, VoiceStateChanged):
            if event.new_state == VoiceState.ERROR:
                renderer.print_error("Voice entered a failed state; disabling voice mode")
                return self._stop_voice()

        return None

    async def _send_voice_transcription(self, text: str) -> None:
        """Send voice transcription to SpokeCore.

        Args:
            text: The transcribed text
        """
        if self._session_id:
            self._response_event.clear()
            await self._core.send_message(self._session_id, text)
            await self._response_event.wait()

    def _voice_response_handler(self, text: str) -> str:
        """Handle voice transcription (sync callback from voice thread).

        This is called by VoiceCore when STT completes. We don't use this
        for the CLI - instead we handle VoiceTranscription events and route
        them through SpokeCore. Return empty string to skip VoiceCore's TTS.

        Args:
            text: Transcribed text

        Returns:
            Empty string (we handle TTS via SpokeCore events)
        """
        # Return empty - we handle this via events and SpokeCore
        return ""


def main() -> None:
    """CLI entrypoint."""
    _configure_cli_logging()
    _load_core_types()
    app = CLIApp()
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        print()  # Clean exit on Ctrl+C


if __name__ == "__main__":
    main()
