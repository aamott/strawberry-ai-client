"""CLI entrypoint for Strawberry AI Spoke."""

from __future__ import annotations

import argparse
import asyncio
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Protocol

from .adapter import CoreEventAdapter, CoreInterface
from .controls import PromptController, ShortcutAction
from .events import CLIEventType, MessageEvent, VoiceStatusEvent
from .renderer import CLIRenderer


class CoreFactory(Protocol):
    """Factory for creating the core interface."""

    def __call__(self, config_path: Optional[Path]) -> CoreInterface:  # pragma: no cover
        ...


@dataclass
class CLIConfig:
    """Configuration for CLI application.

    Args:
        config_path: Optional path to the config file.
        shortcuts_text: Text to render on the left of the status bar.
    """

    config_path: Optional[Path]
    shortcuts_text: str


class FallbackCore(CoreInterface):
    """Fallback core used when SpokeCore is unavailable.

    This keeps the CLI usable in a limited mode, emitting simple message events.
    """

    def __init__(self) -> None:
        self._handlers: List[Callable[[object], None]] = []

    def subscribe(self, handler: Callable[[object], None]) -> None:
        self._handlers.append(handler)

    async def start(self) -> None:
        self._emit(
            MessageEvent(
                type=CLIEventType.MESSAGE,
                role="system",
                content=(
                    "SpokeCore not available. Running in echo mode. "
                    "Tool calls and voice are disabled."
                ),
            )
        )

    async def stop(self) -> None:
        return None

    def new_session(self) -> str:
        return str(uuid.uuid4())

    async def send_user_message(self, session_id: str, text: str) -> None:
        self._emit(
            MessageEvent(
                type=CLIEventType.MESSAGE,
                session_id=session_id,
                role="user",
                content=text,
            )
        )
        self._emit(
            MessageEvent(
                type=CLIEventType.MESSAGE,
                session_id=session_id,
                role="assistant",
                content=f"Echo: {text}",
            )
        )

    async def start_voice(self) -> None:
        self._emit(
            VoiceStatusEvent(
                type=CLIEventType.VOICE_STATUS,
                status="muted",
            )
        )

    async def stop_voice(self) -> None:
        self._emit(
            VoiceStatusEvent(
                type=CLIEventType.VOICE_STATUS,
                status="muted",
            )
        )

    def _emit(self, event: object) -> None:
        for handler in self._handlers:
            handler(event)


class CLIApp:
    """Run the CLI UI for Strawberry AI Spoke."""

    def __init__(
        self,
        config: CLIConfig,
        core_factory: Optional[CoreFactory] = None,
    ) -> None:
        self._config = config
        self._core_factory = core_factory or _default_core_factory
        self._renderer = CLIRenderer(shortcuts_text=config.shortcuts_text)
        self._adapter = CoreEventAdapter(self._renderer)
        self._voice_enabled = False
        self._prompt = PromptController(self._handle_shortcut)
        self._core: Optional[CoreInterface] = None
        self._session_id: Optional[str] = None

    async def run(self) -> int:
        """Run the CLI application.

        Returns:
            Exit code.
        """
        core = self._core_factory(self._config.config_path)
        self._core = core
        await core.start()
        session_id = core.new_session()
        self._session_id = session_id
        self._adapter.set_session_id(session_id)
        self._adapter.bind(core)

        self._print_header()
        self._renderer.render_status_bar()

        while True:
            try:
                user_input = (await self._prompt.prompt()).strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not user_input:
                continue

            if await self._handle_command(user_input, core):
                if user_input in ("/q", "exit"):
                    break
                continue

            if self._session_id is None:
                self._session_id = core.new_session()
                self._adapter.set_session_id(self._session_id)
            await core.send_user_message(self._session_id, user_input)

        await core.stop()
        self._core = None
        return 0

    def _print_header(self) -> None:
        """Print the CLI header."""
        print("\nStrawberry CLI")
        print("-" * 40)
        print("Type /h for help. Use Shift+Tab to expand tool output.")
        print("-" * 40)

    async def _handle_command(self, user_input: str, core: CoreInterface) -> bool:
        """Handle command inputs.

        Args:
            user_input: User input string.
            core: Core interface instance.

        Returns:
            True if the command was handled.
        """
        command = user_input.strip()
        if command in ("/q", "exit"):
            return True
        if command == "/h":
            self._print_help()
            return True
        if command == "/c":
            session_id = core.new_session()
            self._session_id = session_id
            self._adapter.set_session_id(session_id)
            print("Conversation cleared.")
            return True
        if command == "/last":
            if not self._renderer.show_last_tool_result():
                print("No tool results to expand.")
            return True
        if command.startswith("/voice"):
            await self._handle_voice_command(command, core)
            return True
        return False

    def _print_help(self) -> None:
        """Print CLI help text."""
        print("\nCommands:")
        print("  /h      Show help")
        print("  /c      Clear conversation")
        print("  /last   Show last tool output")
        print("  /voice  Toggle voice on/off")
        print("  /q      Quit")
        print()

    async def _handle_voice_command(self, command: str, core: CoreInterface) -> None:
        """Toggle or set the voice mode.

        Args:
            command: Voice command string.
            core: Core interface instance.
        """
        tokens = command.split()
        action = tokens[1] if len(tokens) > 1 else "toggle"

        if action in ("on", "start"):
            await core.start_voice()
            self._voice_enabled = True
            self._renderer.render_voice_status(
                VoiceStatusEvent(type=CLIEventType.VOICE_STATUS, status="waiting")
            )
            return

        if action in ("off", "stop"):
            await core.stop_voice()
            self._voice_enabled = False
            self._renderer.render_voice_status(
                VoiceStatusEvent(type=CLIEventType.VOICE_STATUS, status="muted")
            )
            return

        if self._voice_enabled:
            await core.stop_voice()
            self._voice_enabled = False
            self._renderer.render_voice_status(
                VoiceStatusEvent(type=CLIEventType.VOICE_STATUS, status="muted")
            )
            return

        await core.start_voice()
        self._voice_enabled = True
        self._renderer.render_voice_status(
            VoiceStatusEvent(type=CLIEventType.VOICE_STATUS, status="waiting")
        )

    def _handle_shortcut(self, action: ShortcutAction) -> None:
        """Handle shortcut actions from the prompt controller."""
        if action == ShortcutAction.TOGGLE_TOOL_RESULT:
            if not self._renderer.toggle_latest_tool_result():
                print("No tool results to expand.")
            return
        if action == ShortcutAction.TOGGLE_VOICE:
            if self._core is None:
                print("Voice toggle unavailable (core not running).")
                return
            asyncio.create_task(self._handle_voice_command("/voice", self._core))


def _default_core_factory(config_path: Optional[Path]) -> CoreInterface:
    """Create a core instance if available, otherwise fall back.

    Args:
        config_path: Optional config file path.

    Returns:
        Core interface implementation.
    """
    try:
        from strawberry.core.app import SpokeCore  # type: ignore

        return SpokeCore(config_path=config_path)
    except Exception:
        return FallbackCore()


def _build_config(args: argparse.Namespace) -> CLIConfig:
    """Build CLI configuration from CLI arguments."""
    shortcuts_text = "Alt+V Voice | Shift+Tab Expand | /h Help"
    return CLIConfig(config_path=args.config, shortcuts_text=shortcuts_text)


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Strawberry AI Spoke - CLI",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config file (optional)",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entrypoint."""
    args = _parse_args()
    config = _build_config(args)
    app = CLIApp(config)
    return asyncio.run(app.run())
