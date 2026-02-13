"""TestRunner - simplified SpokeCore wrapper for testing."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ToolCallRecord:
    """Record of a single tool call."""

    name: str
    arguments: Dict[str, Any]
    result: Optional[str] = None
    error: Optional[str] = None
    success: bool = True


@dataclass
class TestResult:
    """Result of a test message."""

    success: bool
    response: Optional[str] = None
    tool_calls: List[ToolCallRecord] = field(default_factory=list)
    error: Optional[str] = None
    duration_ms: int = 0
    mode: str = "local"


class TestRunner:
    """Simplified SpokeCore wrapper for testing.

    Provides a clean interface for sending messages and collecting
    structured results including all tool calls.
    """

    def __init__(
        self,
        config_dir: Optional[Path] = None,
        offline: bool = False,
        filter_logs: bool = True,
        on_event: Optional[Callable[[str, Any], None]] = None,
    ) -> None:
        """Initialize TestRunner.

        Args:
            config_dir: Path to config directory. Defaults to project config/.
            offline: If True, skip hub connection.
            filter_logs: If True, suppress TensorZero/Rust logs.
            on_event: Optional callback for streaming events.
                Called with (event_type, data) for real-time output.
                event_type: 'tool_start', 'tool_result', 'assistant', 'error'
        """
        self._config_dir = config_dir
        self._offline = offline
        self._filter_logs = filter_logs
        self._on_event = on_event

        self._core = None
        self._session_id: Optional[str] = None
        self._subscription = None

        # Collect events during message processing
        self._current_tool_calls: List[ToolCallRecord] = []
        self._current_response: Optional[str] = None
        self._current_error: Optional[str] = None
        self._response_event = asyncio.Event()

    async def start(self) -> None:
        """Initialize SpokeCore and create session."""
        # Import after logging is configured
        from ...shared.settings import SettingsManager
        from ...spoke_core import SpokeCore
        from ...utils.paths import get_project_root

        # Setup config
        if self._config_dir is None:
            self._config_dir = get_project_root() / "config"

        settings_manager = SettingsManager(
            config_dir=self._config_dir,
            env_filename="../.env",
        )

        self._core = SpokeCore(settings_manager=settings_manager)
        await self._core.start()

        # Create session
        session = self._core.new_session()
        self._session_id = session.id

        # Subscribe to events
        self._subscription = self._core.subscribe(self._handle_event)

        # Connect to hub unless offline mode
        if not self._offline:
            try:
                await self._core.connect_hub()
            except Exception as e:
                logger.warning(f"Hub connection failed: {e}")

    async def stop(self) -> None:
        """Cleanup resources."""
        if self._subscription:
            self._subscription.cancel()
            self._subscription = None

        if self._core:
            await self._core.stop()
            self._core = None

    async def send(self, message: str, timeout: float = 120.0) -> TestResult:
        """Send a message and wait for response.

        Args:
            message: User message to send.
            timeout: Timeout in seconds.

        Returns:
            TestResult with response and tool calls.
        """
        if not self._core or not self._session_id:
            return TestResult(
                success=False,
                error="Runner not started",
            )

        # Reset state for new message
        self._current_tool_calls = []
        self._current_response = None
        self._current_error = None
        self._response_event.clear()

        start_time = time.monotonic()

        try:
            # Send message (this runs the agent loop)
            await asyncio.wait_for(
                self._core.send_message(self._session_id, message),
                timeout=timeout,
            )

            # Wait for response event (set by MessageAdded handler)
            await asyncio.wait_for(
                self._response_event.wait(),
                timeout=timeout,
            )

        except asyncio.TimeoutError:
            return TestResult(
                success=False,
                error=f"Timeout after {timeout}s",
                tool_calls=self._current_tool_calls,
                duration_ms=int((time.monotonic() - start_time) * 1000),
                mode=self._get_mode(),
            )
        except Exception as e:
            return TestResult(
                success=False,
                error=str(e),
                tool_calls=self._current_tool_calls,
                duration_ms=int((time.monotonic() - start_time) * 1000),
                mode=self._get_mode(),
            )

        duration_ms = int((time.monotonic() - start_time) * 1000)

        return TestResult(
            success=self._current_error is None,
            response=self._current_response,
            tool_calls=self._current_tool_calls,
            error=self._current_error,
            duration_ms=duration_ms,
            mode=self._get_mode(),
        )

    def _get_mode(self) -> str:
        """Get current mode string."""
        if self._core and self._core.is_online():
            return "online"
        return "local"

    def _handle_event(self, event: Any) -> None:
        """Handle SpokeCore events.

        Args:
            event: CoreEvent instance.
        """
        # Import event types
        from ...spoke_core import (
            CoreError,
            MessageAdded,
            ToolCallResult,
            ToolCallStarted,
        )

        if isinstance(event, ToolCallStarted):
            # Start tracking a new tool call
            record = ToolCallRecord(
                name=event.tool_name,
                arguments=event.arguments,
            )
            self._current_tool_calls.append(record)

            # Stream event
            if self._on_event:
                self._on_event("tool_start", record)

        elif isinstance(event, ToolCallResult):
            # Update the matching tool call with result
            for tc in reversed(self._current_tool_calls):
                if tc.name == event.tool_name and tc.result is None:
                    tc.success = event.success
                    tc.result = event.result
                    tc.error = event.error

                    # Stream event
                    if self._on_event:
                        self._on_event("tool_result", tc)
                    break

        elif isinstance(event, MessageAdded):
            if event.role == "assistant":
                self._current_response = event.content
                self._response_event.set()

                # Stream event
                if self._on_event:
                    self._on_event("assistant", event.content)

        elif isinstance(event, CoreError):
            self._current_error = event.error
            self._response_event.set()
