"""Assistant turn widget."""
from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..markdown_renderer import render_markdown
from ..theme import Theme


class AssistantTurnWidget(QFrame):
    """Assistant message bubble for Strawberry."""

    def __init__(
        self,
        content: str,
        timestamp: Optional[datetime] = None,
        theme: Optional[Theme] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        self._markdown = content
        self.timestamp = timestamp or datetime.now()
        self._theme = theme

        self._setup_ui()

    def _setup_ui(self):
        outer_layout = QHBoxLayout(self)
        outer_layout.setContentsMargins(8, 4, 8, 4)

        self._bubble = QFrame()
        self._bubble.setObjectName("assistantTurn")
        self._bubble_layout = QVBoxLayout(self._bubble)
        self._bubble_layout.setContentsMargins(12, 8, 12, 8)
        self._bubble_layout.setSpacing(6)

        # Sender label
        sender = QLabel("Strawberry")
        sender.setObjectName("senderLabel")
        sender_font = QFont()
        sender_font.setWeight(QFont.Weight.DemiBold)
        sender_font.setPointSize(11)
        sender.setFont(sender_font)
        self._bubble_layout.addWidget(sender)
        self._sender_label = sender

        # Content container (will hold text labels and code/output block widgets)
        self._message_label = QLabel()
        self._message_label.setObjectName("messageLabel")
        self._message_label.setWordWrap(True)
        self._message_label.setTextFormat(Qt.TextFormat.RichText)
        self._message_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self._message_label.setOpenExternalLinks(True)
        self._message_label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        self._bubble_layout.addWidget(self._message_label)

        # Render initial content
        self._render_message()

        # Timestamp
        time_str = self.timestamp.strftime("%H:%M")
        time_label = QLabel(time_str)
        time_label.setObjectName("timeLabel")
        time_label.setProperty("muted", True)
        time_font = QFont()
        time_font.setPointSize(10)
        time_label.setFont(time_font)
        self._bubble_layout.addWidget(time_label)
        self._time_label = time_label

        # Bubble sizing
        self._bubble.setMinimumWidth(100)
        self._bubble.setMaximumWidth(1200)  # Increased for better readability
        self._bubble.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum)

        outer_layout.addWidget(self._bubble)
        outer_layout.addStretch()

        self._apply_style()

    def _render_message(self) -> None:
        """Render markdown content as HTML."""
        html_content = render_markdown(self._markdown or "", self._theme)
        self._message_label.setText(html_content)

        if self._theme:
            self._message_label.setStyleSheet(
                f"color: {self._theme.ai_text}; background: transparent;"
            )

    def set_markdown(self, content: str) -> None:
        """Replace markdown content and re-render."""
        self._markdown = content
        self._render_message()

    def append_markdown(self, content: str) -> None:
        """Append to markdown content and re-render."""
        if not self._markdown:
            self._markdown = content
        else:
            self._markdown = f"{self._markdown}\n\n{content}"
        self._render_message()

    def _apply_style(self):
        """Apply theme-based styling."""
        if not self._theme:
            return

        bg = self._theme.ai_bubble
        text = self._theme.ai_text

        self._bubble.setStyleSheet(
            f"""
                QFrame#assistantTurn {{
                    background-color: {bg};
                    border-radius: 12px;
                }}
            """
        )

        self._sender_label.setStyleSheet(f"color: {text}; background: transparent;")
        self._time_label.setStyleSheet(
            f"color: {self._theme.text_muted}; background: transparent;"
        )

    def set_theme(self, theme: Theme):
        """Update the widget's theme."""
        self._theme = theme
        self._apply_style()
        self._render_message()
