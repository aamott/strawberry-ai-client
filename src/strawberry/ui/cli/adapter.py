"""Adapter for bridging core events to CLI rendering."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable, Optional, Protocol

from .events import (
    CLIEvent,
    CLIEventType,
    ErrorEvent,
    MessageEvent,
    ToolCallEvent,
    ToolResultEvent,
    VoiceStatusEvent,
)
from .renderer import CLIRenderer


class CoreInterface(Protocol):
    """Protocol for the Spoke Core interface expected by the CLI."""

    def subscribe(self, handler: Callable[[Any], None]) -> None:
        """Subscribe to core events."""

    async def start(self) -> None:
        """Start the core runtime."""

    async def stop(self) -> None:
        """Stop the core runtime."""

    def new_session(self) -> str:
        """Create a new chat session and return its ID."""

    async def send_user_message(self, session_id: str, text: str) -> None:
        """Send a user message to the core."""

    async def start_voice(self) -> None:
        """Start the voice pipeline."""

    async def stop_voice(self) -> None:
        """Stop the voice pipeline."""


class CoreEventAdapter:
    """Translate core events into CLI rendering calls.

    Args:
        renderer: Renderer instance for CLI output.
        session_id: Optional active session identifier.
    """

    def __init__(self, renderer: CLIRenderer, session_id: Optional[str] = None) -> None:
        self._renderer = renderer
        self._session_id = session_id

    def bind(self, core: CoreInterface) -> None:
        """Bind to the core event stream."""
        core.subscribe(self.handle_event)

    def set_session_id(self, session_id: Optional[str]) -> None:
        """Update the active session id.

        Args:
            session_id: Active session identifier.
        """
        self._session_id = session_id

    def handle_event(self, event: Any) -> None:
        """Handle a core event and render it.

        Args:
            event: Core event payload or CLI event.
        """
        cli_event = self._to_cli_event(event)
        if not cli_event:
            return

        if cli_event.type == CLIEventType.MESSAGE and isinstance(cli_event, MessageEvent):
            self._renderer.render_message(cli_event)
            return
        if cli_event.type == CLIEventType.TOOL_CALL and isinstance(
            cli_event, ToolCallEvent
        ):
            self._renderer.render_tool_call(cli_event)
            return
        if cli_event.type == CLIEventType.TOOL_RESULT and isinstance(
            cli_event, ToolResultEvent
        ):
            self._renderer.render_tool_result(cli_event)
            return
        if cli_event.type == CLIEventType.VOICE_STATUS and isinstance(
            cli_event, VoiceStatusEvent
        ):
            self._renderer.render_voice_status(cli_event)
            return
        if cli_event.type == CLIEventType.ERROR and isinstance(cli_event, ErrorEvent):
            self._renderer.render_error(cli_event)

    def _to_cli_event(self, event: Any) -> Optional[CLIEvent]:
        """Convert raw core events into CLI events.

        Args:
            event: Core event payload or CLI event.

        Returns:
            Parsed CLI event, or None if unsupported.
        """
        if isinstance(event, CLIEvent):
            return event

        if isinstance(event, dict):
            return self._from_mapping(event)

        if hasattr(event, "type"):
            return self._from_object(event)

        if hasattr(event, "role") and hasattr(event, "content"):
            return MessageEvent(
                type=CLIEventType.MESSAGE,
                session_id=self._session_id,
                role=getattr(event, "role", "assistant"),
                content=getattr(event, "content", ""),
                metadata={},
            )

        return None

    def _from_mapping(self, payload: dict[str, Any]) -> Optional[CLIEvent]:
        """Build a CLI event from a mapping payload."""
        event_type = payload.get("type")
        if isinstance(event_type, CLIEventType):
            return self._from_cli_mapping(payload, event_type)
        if isinstance(event_type, str) and event_type in CLIEventType._value2member_map_:
            return self._from_cli_mapping(payload, CLIEventType(event_type))
        if "role" in payload and "content" in payload:
            return MessageEvent(
                type=CLIEventType.MESSAGE,
                session_id=payload.get("session_id"),
                role=payload.get("role", "assistant"),
                content=payload.get("content", ""),
                metadata=payload.get("metadata") or {},
            )
        return None

    def _from_object(self, event: Any) -> Optional[CLIEvent]:
        """Convert a typed core event object to a CLI event."""
        event_type = getattr(event, "type", None)
        if isinstance(event_type, CLIEventType):
            return self._from_cli_mapping(asdict(event), event_type)
        if isinstance(event_type, str) and event_type in CLIEventType._value2member_map_:
            return self._from_cli_mapping(asdict(event), CLIEventType(event_type))
        if hasattr(event, "status"):
            return VoiceStatusEvent(
                type=CLIEventType.VOICE_STATUS,
                session_id=getattr(event, "session_id", None),
                status=getattr(event, "status", "waiting"),
            )
        return None

    def _from_cli_mapping(self, payload: dict[str, Any], event_type: CLIEventType) -> CLIEvent:
        """Convert a mapping payload into a CLI event."""
        if event_type == CLIEventType.MESSAGE:
            return MessageEvent(
                type=event_type,
                session_id=payload.get("session_id"),
                role=payload.get("role", "assistant"),
                content=payload.get("content", ""),
                metadata=payload.get("metadata") or {},
            )
        if event_type == CLIEventType.TOOL_CALL:
            return ToolCallEvent(
                type=event_type,
                session_id=payload.get("session_id"),
                tool_name=payload.get("tool_name", ""),
                preview=payload.get("preview", ""),
                arguments=payload.get("arguments") or {},
                tool_call_id=payload.get("tool_call_id"),
            )
        if event_type == CLIEventType.TOOL_RESULT:
            return ToolResultEvent(
                type=event_type,
                session_id=payload.get("session_id"),
                tool_name=payload.get("tool_name", ""),
                preview=payload.get("preview", ""),
                content=payload.get("content", ""),
                success=payload.get("success", True),
                error=payload.get("error"),
                tool_call_id=payload.get("tool_call_id"),
            )
        if event_type == CLIEventType.VOICE_STATUS:
            return VoiceStatusEvent(
                type=event_type,
                session_id=payload.get("session_id"),
                status=payload.get("status", "waiting"),
            )
        if event_type == CLIEventType.ERROR:
            return ErrorEvent(
                type=event_type,
                session_id=payload.get("session_id"),
                message=payload.get("message", ""),
            )
        return CLIEvent(type=event_type, session_id=payload.get("session_id"))
