"""Message models for GUI V2."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Union


class MessageRole(Enum):
    """Role of the message sender."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class SegmentType(Enum):
    """Type of content segment within a message."""
    TEXT = "text"
    TOOL_CALL = "tool_call"


@dataclass
class TextSegment:
    """A markdown text segment within a message."""
    content: str = ""
    type: SegmentType = field(default=SegmentType.TEXT, init=False)


@dataclass
class ToolCallSegment:
    """A tool call segment with expandable details.

    Attributes:
        tool_name: Full tool name (e.g., "WeatherSkill.get_current_weather")
        arguments: Tool call arguments as a dictionary
        result: Tool result string (None if pending)
        error: Error message if the tool call failed
        duration_ms: Execution time in milliseconds
        expanded: UI state - whether details are expanded
    """
    tool_name: str = ""
    arguments: Optional[dict] = None
    result: Optional[str] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    expanded: bool = False
    type: SegmentType = field(default=SegmentType.TOOL_CALL, init=False)


# Union type for content segments
ContentSegment = Union[TextSegment, ToolCallSegment]


@dataclass
class Message:
    """A chat message containing one or more content segments.

    For user messages, typically contains a single TextSegment.
    For assistant messages, may contain interleaved TextSegments and ToolCallSegments.

    Attributes:
        id: Unique message identifier
        role: Message sender role (user/assistant/system)
        timestamp: When the message was created
        segments: Ordered list of content segments
        is_streaming: Whether the message is currently being streamed
    """
    id: str
    role: MessageRole
    timestamp: datetime = field(default_factory=datetime.now)
    segments: List[ContentSegment] = field(default_factory=list)
    is_streaming: bool = False

    def get_text_content(self) -> str:
        """Get all text content concatenated."""
        return "".join(
            seg.content for seg in self.segments
            if isinstance(seg, TextSegment)
        )

    def add_text(self, content: str) -> None:
        """Add or append text content.

        If the last segment is a TextSegment, appends to it.
        Otherwise, creates a new TextSegment.
        """
        if self.segments and isinstance(self.segments[-1], TextSegment):
            self.segments[-1].content += content
        else:
            self.segments.append(TextSegment(content=content))

    def add_tool_call(
        self,
        tool_name: str,
        arguments: Optional[dict] = None,
    ) -> ToolCallSegment:
        """Add a new tool call segment.

        Returns the created segment for later updates.
        """
        segment = ToolCallSegment(
            tool_name=tool_name,
            arguments=arguments,
        )
        self.segments.append(segment)
        return segment

    def update_tool_call(
        self,
        tool_name: str,
        result: Optional[str] = None,
        error: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> bool:
        """Update a pending tool call with its result.

        Finds the first matching tool call without a result and updates it.

        Returns:
            True if a tool call was updated, False if not found.
        """
        for seg in self.segments:
            if (isinstance(seg, ToolCallSegment) and
                seg.tool_name == tool_name and
                seg.result is None and
                seg.error is None):
                seg.result = result
                seg.error = error
                seg.duration_ms = duration_ms
                return True
        return False
