"""Input handling and shortcut bindings for the CLI UI."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.key_binding import KeyBindings
except ImportError:  # pragma: no cover - optional dependency
    PromptSession = None
    KeyBindings = None


class ShortcutAction(str, Enum):
    """Supported shortcut actions."""

    TOGGLE_TOOL_RESULT = "toggle_tool_result"
    TOGGLE_VOICE = "toggle_voice"


@dataclass
class PromptConfig:
    """Configuration for prompt behavior.

    Args:
        prompt_text: Prompt prefix text.
    """

    prompt_text: str = "> "


class PromptController:
    """Handle user input with optional key bindings.

    Args:
        on_shortcut: Callback invoked when a shortcut is triggered.
        config: Prompt configuration.
    """

    def __init__(
        self,
        on_shortcut: Callable[[ShortcutAction], None],
        config: Optional[PromptConfig] = None,
    ) -> None:
        self._on_shortcut = on_shortcut
        self._config = config or PromptConfig()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._session = self._build_session()

    async def prompt(self) -> str:
        """Prompt the user for input.

        Returns:
            User input string.
        """
        self._loop = asyncio.get_running_loop()
        if self._session and hasattr(self._session, "prompt_async"):
            return await self._session.prompt_async(self._config.prompt_text)
        return await asyncio.to_thread(self._prompt_sync)

    def supports_shortcuts(self) -> bool:
        """Return True if key bindings are available."""
        return self._session is not None

    def _prompt_sync(self) -> str:
        """Run a synchronous prompt."""
        if self._session:
            return self._session.prompt(self._config.prompt_text)
        return input(self._config.prompt_text)

    def _build_session(self) -> Optional[PromptSession]:
        """Create a prompt_toolkit session when available."""
        if PromptSession is None or KeyBindings is None:
            return None

        bindings = KeyBindings()

        @bindings.add("s-tab")
        def _toggle_tool_result(_event) -> None:
            self._dispatch_shortcut(ShortcutAction.TOGGLE_TOOL_RESULT)

        @bindings.add("escape", "v")
        def _toggle_voice(_event) -> None:
            self._dispatch_shortcut(ShortcutAction.TOGGLE_VOICE)

        return PromptSession(key_bindings=bindings)

    def _dispatch_shortcut(self, action: ShortcutAction) -> None:
        """Dispatch a shortcut event on the main loop.

        Args:
            action: Shortcut action.
        """
        if self._loop:
            self._loop.call_soon_threadsafe(self._on_shortcut, action)
        else:
            self._on_shortcut(action)
