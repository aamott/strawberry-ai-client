"""Event models for the CLI UI layer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class CLIEventType(str, Enum):
    """Supported event types for the CLI UI."""

    READY = "ready"
    MESSAGE = "message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    VOICE_STATUS = "voice_status"
    ERROR = "error"


@dataclass
class CLIEvent:
    """Base event for CLI rendering.

    Args:
        type: Event type.
        session_id: Optional session identifier.
    """

    type: CLIEventType
    session_id: Optional[str] = None


@dataclass
class MessageEvent(CLIEvent):
    """Represents a chat message to render.

    Args:
        role: Message role (user, assistant, system).
        content: Message content.
        metadata: Optional metadata for tool calls or extra info.
    """

    role: str = "assistant"
    content: str = ""
    metadata: Dict[str, Any] = None


@dataclass
class ToolCallEvent(CLIEvent):
    """Represents a tool call summary.

    Args:
        tool_name: Tool name.
        preview: Short argument preview.
        arguments: Full tool args.
        tool_call_id: Optional tool call identifier.
    """

    tool_name: str = ""
    preview: str = ""
    arguments: Dict[str, Any] = None
    tool_call_id: Optional[str] = None


@dataclass
class ToolResultEvent(CLIEvent):
    """Represents a tool result.

    Args:
        tool_name: Tool name.
        preview: Preview string for collapsed display.
        content: Full tool output.
        success: Whether the tool call was successful.
        error: Optional error message.
        tool_call_id: Optional tool call identifier.
    """

    tool_name: str = ""
    preview: str = ""
    content: str = ""
    success: bool = True
    error: Optional[str] = None
    tool_call_id: Optional[str] = None


@dataclass
class VoiceStatusEvent(CLIEvent):
    """Represents a voice status change.

    Args:
        status: Status string.
    """

    status: str = "waiting"


@dataclass
class ErrorEvent(CLIEvent):
    """Represents an error to display.

    Args:
        message: Error text.
    """

    message: str = ""
