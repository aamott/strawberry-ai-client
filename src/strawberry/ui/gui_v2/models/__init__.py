"""GUI V2 Models - Data structures for the UI."""

from .message import ContentSegment, Message, MessageRole, TextSegment, ToolCallSegment
from .state import UIState

__all__ = [
    "MessageRole",
    "TextSegment",
    "ToolCallSegment",
    "ContentSegment",
    "Message",
    "UIState",
]
