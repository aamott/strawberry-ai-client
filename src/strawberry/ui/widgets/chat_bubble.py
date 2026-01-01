"""Chat message bubble widget."""

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..markdown_renderer import render_markdown
from ..theme import Theme


class ChatBubble(QFrame):
    """A chat message bubble.
    
    Displays a message with sender info and timestamp.
    Supports user messages (right-aligned) and AI messages (left-aligned).
    """

    def __init__(
        self,
        content: str,
        is_user: bool = True,
        timestamp: Optional[datetime] = None,
        theme: Optional[Theme] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        self.content = content
        self.is_user = is_user
        self.timestamp = timestamp or datetime.now()
        self._theme = theme

        self._setup_ui()

    def _setup_ui(self):
        """Set up the bubble UI."""
        # Main horizontal layout for alignment
        outer_layout = QHBoxLayout(self)
        outer_layout.setContentsMargins(8, 4, 8, 4)

        if self.is_user:
            outer_layout.addStretch()

        # Bubble container
        bubble = QFrame()
        bubble.setObjectName("chatBubble")
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(12, 8, 12, 8)
        bubble_layout.setSpacing(4)

        # Sender label
        sender = QLabel("You" if self.is_user else "Strawberry")
        sender.setObjectName("senderLabel")
        sender_font = QFont()
        sender_font.setWeight(QFont.Weight.DemiBold)
        sender_font.setPointSize(11)
        sender.setFont(sender_font)
        bubble_layout.addWidget(sender)

        # Message content - QLabel with rich text
        message = QLabel()
        message.setObjectName("messageLabel")
        message.setWordWrap(True)
        message.setTextFormat(Qt.TextFormat.RichText)
        message.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse |
            Qt.TextInteractionFlag.TextSelectableByKeyboard |
            Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        message.setOpenExternalLinks(True)
        message.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        # Render content
        if not self.is_user:
            # Render markdown for AI messages
            html_content = render_markdown(self.content, self._theme)
            message.setText(html_content)
        else:
            # Simple HTML for user messages
            escaped = self.content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            escaped = escaped.replace("\n", "<br>")
            message.setText(escaped)

        bubble_layout.addWidget(message)

        # Timestamp
        time_str = self.timestamp.strftime("%H:%M")
        time_label = QLabel(time_str)
        time_label.setObjectName("timeLabel")
        time_label.setProperty("muted", True)
        time_font = QFont()
        time_font.setPointSize(10)
        time_label.setFont(time_font)
        bubble_layout.addWidget(time_label)

        # Bubble sizing
        bubble.setMinimumWidth(100)
        bubble.setMaximumWidth(600)
        bubble.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum)

        outer_layout.addWidget(bubble)

        if not self.is_user:
            outer_layout.addStretch()

        # Apply bubble-specific styling
        self._apply_style(bubble, sender, message, time_label)

    def _apply_style(self, bubble: QFrame, sender: QLabel, message: QLabel, time_label: QLabel):
        """Apply theme-based styling to bubble."""
        if self._theme:
            if self.is_user:
                bg = self._theme.user_bubble
                text = self._theme.user_text
            else:
                bg = self._theme.ai_bubble
                text = self._theme.ai_text

            bubble.setStyleSheet(f"""
                QFrame#chatBubble {{
                    background-color: {bg};
                    border-radius: 12px;
                }}
            """)

            sender.setStyleSheet(f"color: {text}; background: transparent;")
            message.setStyleSheet(f"color: {text}; background: transparent;")
            time_label.setStyleSheet(f"color: {self._theme.text_muted}; background: transparent;")

    def set_theme(self, theme: Theme):
        """Update the bubble's theme."""
        self._theme = theme
        # Would need to re-apply styles - for simplicity, recreate is easier
