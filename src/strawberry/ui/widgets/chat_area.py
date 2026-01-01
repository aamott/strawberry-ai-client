"""Scrollable chat message area."""

from typing import List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from ..theme import Theme
from .assistant_turn_widget import AssistantTurnWidget
from .chat_bubble import ChatBubble
from .tool_call_widget import ToolCallWidget


class ChatArea(QScrollArea):
    """Scrollable area containing chat messages.
    
    Automatically scrolls to bottom when new messages are added.
    """

    def __init__(self, theme: Optional[Theme] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._theme = theme
        self._messages: List[ChatBubble] = []
        self._auto_scroll = True
        self._last_assistant_turn: Optional[AssistantTurnWidget] = None

        self._setup_ui()

    def _setup_ui(self):
        """Set up the chat area."""
        # Scroll area settings
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFrameShape(QFrame.Shape.NoFrame)

        # Container widget
        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 8, 0, 8)
        self._layout.setSpacing(4)
        self._layout.addStretch()

        self.setWidget(self._container)

        # Connect scroll bar to detect manual scrolling
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.verticalScrollBar().rangeChanged.connect(self._on_range_changed)

    def add_message(self, content: str, is_user: bool = True):
        """Add a new message to the chat.
        
        Args:
            content: Message text
            is_user: True for user messages, False for AI
            
        Returns:
            The created ChatBubble widget
        """
        if is_user:
            bubble = ChatBubble(
                content=content,
                is_user=is_user,
                theme=self._theme,
                parent=self._container,
            )
            self._messages.append(bubble)
            self._last_assistant_turn = None
        else:
            bubble = AssistantTurnWidget(
                content=content,
                theme=self._theme,
                parent=self._container,
            )
            self._last_assistant_turn = bubble

        # Insert before the stretch
        self._layout.insertWidget(self._layout.count() - 1, bubble)

        # Schedule scroll to bottom
        if self._auto_scroll:
            QTimer.singleShot(10, self._scroll_to_bottom)

        return bubble

    def add_assistant_turn(self, content: str) -> AssistantTurnWidget:
        bubble = AssistantTurnWidget(
            content=content,
            theme=self._theme,
            parent=self._container,
        )

        self._layout.insertWidget(self._layout.count() - 1, bubble)
        self._last_assistant_turn = bubble

        if self._auto_scroll:
            QTimer.singleShot(10, self._scroll_to_bottom)

        return bubble

    def add_system_message(self, content: str):
        """Add a system/status message (centered, muted)."""
        label = QLabel(content)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setProperty("muted", True)
        label.setWordWrap(True)

        if self._theme:
            label.setStyleSheet(f"""
                color: {self._theme.text_muted};
                background: transparent;
                padding: 8px;
                font-size: 12px;
            """)

        self._layout.insertWidget(self._layout.count() - 1, label)

        if self._auto_scroll:
            QTimer.singleShot(10, self._scroll_to_bottom)

    def add_tool_call(
        self,
        tool_name: str,
        arguments: dict,
    ) -> ToolCallWidget:
        """Add a tool/skill call widget.
        
        Args:
            tool_name: Name of the tool being called
            arguments: Tool arguments
            
        Returns:
            The created ToolCallWidget (can be updated with results)
        """
        if self._last_assistant_turn is not None:
            widget = self._last_assistant_turn.add_tool_call(tool_name=tool_name, arguments=arguments)
        else:
            widget = ToolCallWidget(
                tool_name=tool_name,
                arguments=arguments,
                theme=self._theme,
                parent=self._container,
            )

            # Insert before the stretch
            self._layout.insertWidget(self._layout.count() - 1, widget)

        if self._auto_scroll:
            QTimer.singleShot(10, self._scroll_to_bottom)

        return widget

    def clear_messages(self):
        """Remove all messages from the chat."""
        for msg in self._messages:
            self._layout.removeWidget(msg)
            msg.deleteLater()
        self._messages.clear()

        # Also remove any system messages (QLabels)
        while self._layout.count() > 1:  # Keep the stretch
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def set_theme(self, theme: Theme):
        """Update theme for all messages."""
        self._theme = theme
        # Note: existing bubbles would need to be recreated for theme change
        # For simplicity, theme changes take effect on new messages

    def _scroll_to_bottom(self):
        """Scroll to the bottom of the chat."""
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_scroll(self, value: int):
        """Handle manual scrolling."""
        scrollbar = self.verticalScrollBar()
        # If user scrolled up, disable auto-scroll
        # If at bottom (within 50px), re-enable
        at_bottom = value >= scrollbar.maximum() - 50
        self._auto_scroll = at_bottom

    def _on_range_changed(self, min_val: int, max_val: int):
        """Handle scroll range changes (new content)."""
        if self._auto_scroll:
            self.verticalScrollBar().setValue(max_val)

