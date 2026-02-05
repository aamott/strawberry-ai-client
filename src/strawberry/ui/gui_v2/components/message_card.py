"""Message card component with seamless interleaved content."""

from datetime import datetime
from typing import List, Optional, Union

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..models.message import (
    ContentSegment,
    Message,
    MessageRole,
    TextSegment,
    ToolCallSegment,
)
from ..utils.icons import Icons
from .text_block import TextBlock
from .tool_call_widget import ToolCallWidget


class MessageHeader(QWidget):
    """Header widget showing role and timestamp."""

    def __init__(
        self,
        role: MessageRole,
        timestamp: datetime,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._role = role
        self._timestamp = timestamp
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Initialize the UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(8)

        # Role icon and label
        icon = Icons.USER if self._role == MessageRole.USER else Icons.ASSISTANT
        role_text = "You" if self._role == MessageRole.USER else "Assistant"

        self._role_label = QLabel(f"{icon} {role_text}")
        self._role_label.setObjectName("RoleLabel")
        layout.addWidget(self._role_label)

        # Stretch
        layout.addStretch()

        # Timestamp
        time_str = self._timestamp.strftime("%I:%M %p")
        self._timestamp_label = QLabel(time_str)
        self._timestamp_label.setObjectName("TimestampLabel")
        layout.addWidget(self._timestamp_label)


class MessageCard(QFrame):
    """Message display card with seamless interleaved content.

    Displays a single turn (user or assistant) as a composite of multiple
    content segments. For assistant messages, these segments can be
    interleaved text and tool calls in any order, preserving the exact
    sequence from the LLM response.

    Design Principle: The card appears as one continuous text block.
    Tool calls are inline elements with subtle styling, not nested bubbles.
    Only the outer MessageCard has a visible border/background.

    Signals:
        tool_call_toggled: Emitted when a tool call is expanded/collapsed
                          (int: segment_index, bool: expanded)
        content_changed: Emitted when any content updates
    """

    tool_call_toggled = Signal(int, bool)
    content_changed = Signal()

    def __init__(
        self,
        message: Optional[Message] = None,
        role: Optional[MessageRole] = None,
        timestamp: Optional[datetime] = None,
        parent: Optional[QWidget] = None,
    ):
        """Initialize the message card.

        Args:
            message: Message model to display (preferred)
            role: Message role (if not using message model)
            timestamp: Message timestamp (if not using message model)
            parent: Parent widget
        """
        super().__init__(parent)

        if message:
            self._message = message
        else:
            # Create a minimal message if not provided
            self._message = Message(
                id="",
                role=role or MessageRole.ASSISTANT,
                timestamp=timestamp or datetime.now(),
            )

        self._segment_widgets: List[Union[TextBlock, ToolCallWidget]] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Initialize the UI layout."""
        self.setObjectName("MessageCard")
        self.setProperty("role", self._message.role.value)

        # Size policy: expand horizontally, fit content vertically
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(0)  # Minimal spacing for seamless flow

        # Header with role and timestamp
        self._header = MessageHeader(self._message.role, self._message.timestamp)
        layout.addWidget(self._header)

        # Separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setObjectName("MessageSeparator")
        layout.addWidget(separator)

        # Content container for segments
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 8, 0, 0)
        self._content_layout.setSpacing(8)  # Small spacing between segments
        layout.addWidget(self._content)

        # Render existing segments
        for segment in self._message.segments:
            self._add_segment_widget(segment)

    def _add_segment_widget(self, segment: ContentSegment) -> Union[TextBlock, ToolCallWidget]:
        """Create and add a widget for a content segment.

        Args:
            segment: The content segment to render

        Returns:
            The created widget
        """
        if isinstance(segment, TextSegment):
            widget = TextBlock(segment.content)
            widget.height_changed.connect(lambda _: self.content_changed.emit())
        else:  # ToolCallSegment
            widget = ToolCallWidget(
                tool_name=segment.tool_name,
                arguments=segment.arguments,
                result=segment.result,
                error=segment.error,
                duration_ms=segment.duration_ms,
                expanded=segment.expanded,
            )
            # Connect toggle signal with segment index
            idx = len(self._segment_widgets)
            widget.toggled.connect(lambda exp, i=idx: self._on_tool_toggled(i, exp))
            widget.height_changed.connect(lambda _: self.content_changed.emit())

        self._content_layout.addWidget(widget)
        self._segment_widgets.append(widget)
        return widget

    def _on_tool_toggled(self, index: int, expanded: bool) -> None:
        """Handle tool call expand/collapse.

        Args:
            index: Segment index
            expanded: New expanded state
        """
        # Update the segment model
        if index < len(self._message.segments):
            segment = self._message.segments[index]
            if isinstance(segment, ToolCallSegment):
                segment.expanded = expanded

        self.tool_call_toggled.emit(index, expanded)
        self.content_changed.emit()

    def append_text(self, content: str) -> None:
        """Append text content (for streaming).

        If the last segment is a TextSegment, appends to it.
        Otherwise, creates a new TextSegment.

        Args:
            content: Text to append
        """
        if (self._message.segments and
            isinstance(self._message.segments[-1], TextSegment) and
            self._segment_widgets and
            isinstance(self._segment_widgets[-1], TextBlock)):
            # Append to existing text segment
            self._message.segments[-1].content += content
            self._segment_widgets[-1].append_content(content)
        else:
            # Create new text segment
            segment = TextSegment(content=content)
            self._message.segments.append(segment)
            self._add_segment_widget(segment)

        self.content_changed.emit()

    def add_tool_call(
        self,
        tool_name: str,
        arguments: Optional[dict] = None,
    ) -> int:
        """Add a new tool call segment.

        Args:
            tool_name: Name of the tool being called
            arguments: Tool call arguments

        Returns:
            Index of the new segment
        """
        segment = ToolCallSegment(
            tool_name=tool_name,
            arguments=arguments,
            expanded=False,
        )
        self._message.segments.append(segment)
        self._add_segment_widget(segment)
        self.content_changed.emit()
        return len(self._message.segments) - 1

    def update_tool_call(
        self,
        tool_name: str,
        result: Optional[str] = None,
        error: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> bool:
        """Update a pending tool call with its result.

        Finds the first matching pending tool call and updates it.

        Args:
            tool_name: Name of the tool to update
            result: Tool result (mutually exclusive with error)
            error: Error message (mutually exclusive with result)
            duration_ms: Execution time in milliseconds

        Returns:
            True if a tool call was updated, False if not found
        """
        for i, (segment, widget) in enumerate(zip(self._message.segments, self._segment_widgets)):
            if (isinstance(segment, ToolCallSegment) and
                isinstance(widget, ToolCallWidget) and
                segment.tool_name == tool_name and
                segment.result is None and
                segment.error is None):

                # Update model
                segment.result = result
                segment.error = error
                segment.duration_ms = duration_ms

                # Update widget
                if error:
                    widget.set_error(error)
                else:
                    widget.set_result(result or "", duration_ms)

                self.content_changed.emit()
                return True

        return False

    def set_streaming(self, is_streaming: bool) -> None:
        """Set the streaming state.

        Args:
            is_streaming: Whether the message is currently streaming
        """
        self._message.is_streaming = is_streaming

    def collapse_all_tool_calls(self) -> None:
        """Collapse all tool call widgets."""
        for segment, widget in zip(self._message.segments, self._segment_widgets):
            if isinstance(segment, ToolCallSegment) and isinstance(widget, ToolCallWidget):
                segment.expanded = False
                widget.set_expanded(False)

    def expand_all_tool_calls(self) -> None:
        """Expand all tool call widgets."""
        for segment, widget in zip(self._message.segments, self._segment_widgets):
            if isinstance(segment, ToolCallSegment) and isinstance(widget, ToolCallWidget):
                segment.expanded = True
                widget.set_expanded(True)

    @property
    def message(self) -> Message:
        """Get the message model."""
        return self._message

    @property
    def role(self) -> MessageRole:
        """Get the message role."""
        return self._message.role

    @property
    def is_streaming(self) -> bool:
        """Check if the message is currently streaming."""
        return self._message.is_streaming
