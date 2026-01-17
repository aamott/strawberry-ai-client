"""Core module - single backend interface for all UIs."""

from .app import SpokeCore
from .events import (
    CoreError,
    CoreEvent,
    CoreReady,
    MessageAdded,
    ToolCallResult,
    ToolCallStarted,
)
from .session import ChatSession

__all__ = [
    "SpokeCore",
    "CoreEvent",
    "MessageAdded",
    "ToolCallStarted",
    "ToolCallResult",
    "CoreReady",
    "CoreError",
    "ChatSession",
]
