"""Agent service - bridges SpokeCore to GUI V2."""

import logging
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from ....spoke_core import SpokeCore
    from ....spoke_core.session import ChatSession

logger = logging.getLogger(__name__)


class AgentService(QObject):
    """Service that bridges SpokeCore events to Qt signals.

    Handles:
    - Starting/stopping SpokeCore
    - Sending messages and running agent loop
    - Converting CoreEvents to Qt signals for UI updates

    Signals:
        core_ready: Emitted when SpokeCore is initialized
        core_error: Emitted on errors (str: error message)
        message_added: Emitted when a message is added
                      (str: session_id, str: role, str: content)
        tool_call_started: Emitted when a tool call starts
                          (str: session_id, str: tool_name, dict: arguments)
        tool_call_result: Emitted when a tool call completes
                         (str: session_id, str: tool_name, bool: success,
                          str: result_or_error)
        connection_changed: Emitted when hub connection changes
                           (bool: connected, str: details)
        mode_changed: Emitted when online/offline mode changes
                     (bool: online, str: message)
    """

    core_ready = Signal()
    core_error = Signal(str)
    message_added = Signal(str, str, str)  # session_id, role, content
    tool_call_started = Signal(str, str, dict)  # session_id, tool_name, args
    tool_call_result = Signal(str, str, bool, str)  # session_id, tool_name, success, result
    connection_changed = Signal(bool, str)  # connected, details
    mode_changed = Signal(bool, str)  # online, message

    def __init__(
        self,
        spoke_core: Optional["SpokeCore"] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._core = spoke_core
        self._subscription = None
        self._current_session: Optional["ChatSession"] = None

    def set_core(self, core: "SpokeCore") -> None:
        """Set the SpokeCore instance and subscribe to events."""
        self._core = core
        self._subscribe_to_events()

    def _subscribe_to_events(self) -> None:
        """Subscribe to SpokeCore events."""
        if not self._core:
            return

        # Unsubscribe from previous subscription
        if self._subscription:
            self._subscription.cancel()

        # Subscribe to events
        self._subscription = self._core.subscribe(self._on_core_event)

    def _on_core_event(self, event) -> None:
        """Handle CoreEvent and emit corresponding Qt signal.

        This runs in the asyncio thread, so we use Qt signals
        which are thread-safe.
        """
        from ....spoke_core.events import (
            ConnectionChanged,
            CoreError,
            CoreReady,
            MessageAdded,
            ModeChanged,
            ToolCallResult,
            ToolCallStarted,
        )

        if isinstance(event, CoreReady):
            self.core_ready.emit()

        elif isinstance(event, CoreError):
            self.core_error.emit(event.error)

        elif isinstance(event, MessageAdded):
            self.message_added.emit(
                event.session_id,
                event.role,
                event.content,
            )

        elif isinstance(event, ToolCallStarted):
            self.tool_call_started.emit(
                event.session_id,
                event.tool_name,
                event.arguments or {},
            )

        elif isinstance(event, ToolCallResult):
            result_text = event.result if event.success else (event.error or "Unknown error")
            self.tool_call_result.emit(
                event.session_id,
                event.tool_name,
                event.success,
                result_text or "",
            )

        elif isinstance(event, ConnectionChanged):
            details = event.error if not event.connected else (event.url or "Connected")
            self.connection_changed.emit(event.connected, details or "")

        elif isinstance(event, ModeChanged):
            self.mode_changed.emit(event.online, event.message or "")

    async def start(self) -> None:
        """Start SpokeCore."""
        if self._core:
            await self._core.start()

    async def stop(self) -> None:
        """Stop SpokeCore."""
        if self._core:
            await self._core.stop()

    def new_session(self) -> str:
        """Create a new chat session.

        Returns:
            The new session ID.
        """
        if not self._core:
            raise RuntimeError("SpokeCore not initialized")

        self._current_session = self._core.new_session()
        return self._current_session.id

    def get_current_session_id(self) -> Optional[str]:
        """Get the current session ID."""
        return self._current_session.id if self._current_session else None

    async def send_message(self, text: str) -> Optional[str]:
        """Send a message and run the agent loop.

        Args:
            text: User message content.

        Returns:
            Final assistant response, or None on error.
        """
        if not self._core:
            self.core_error.emit("SpokeCore not initialized")
            return None

        if not self._current_session:
            self._current_session = self._core.new_session()

        return await self._core.send_message(self._current_session.id, text)

    async def connect_hub(self) -> bool:
        """Connect to the Hub.

        Returns:
            True if connection succeeded.
        """
        if not self._core:
            return False
        return await self._core.connect_hub()

    async def disconnect_hub(self) -> None:
        """Disconnect from the Hub."""
        if self._core:
            await self._core.disconnect_hub()

    def is_online(self) -> bool:
        """Check if connected to Hub."""
        return self._core.is_online() if self._core else False

    @property
    def core(self) -> Optional["SpokeCore"]:
        """Get the SpokeCore instance."""
        return self._core
