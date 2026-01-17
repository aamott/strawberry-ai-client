"""Event types for UI updates."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class CoreEvent:
    """Base class for all core events."""
    pass


@dataclass
class CoreReady(CoreEvent):
    """Core is initialized and ready."""
    pass


@dataclass
class CoreError(CoreEvent):
    """Core encountered an error."""
    error: str
    exception: Optional[Exception] = None


@dataclass
class SessionCreated(CoreEvent):
    """A new chat session was created."""
    session_id: str


@dataclass
class MessageAdded(CoreEvent):
    """A message was added to a session."""
    session_id: str
    role: str  # "user", "assistant", "system"
    content: str


@dataclass
class ToolCallStarted(CoreEvent):
    """A tool call has started."""
    session_id: str
    tool_name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallResult(CoreEvent):
    """A tool call completed."""
    session_id: str
    tool_name: str
    success: bool
    result: Optional[str] = None
    error: Optional[str] = None
