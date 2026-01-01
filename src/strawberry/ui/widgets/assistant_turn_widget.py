"""Assistant turn widget (notebook-style).

Renders an assistant message with inline, collapsible tool call/output sections.
"""

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..markdown_renderer import render_markdown
from ..theme import Theme
from .tool_call_widget import ToolCallWidget


class AssistantTurnWidget(QFrame):
    def __init__(
        self,
        content: str,
        timestamp: Optional[datetime] = None,
        theme: Optional[Theme] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        self.content = content
        self.timestamp = timestamp or datetime.now()
        self._theme = theme

        self._setup_ui()

    def _setup_ui(self):
        outer_layout = QHBoxLayout(self)
        outer_layout.setContentsMargins(8, 4, 8, 4)

        bubble = QFrame()
        bubble.setObjectName("assistantTurn")
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(12, 8, 12, 8)
        bubble_layout.setSpacing(6)

        sender = QLabel("Strawberry")
        sender.setObjectName("senderLabel")
        sender_font = QFont()
        sender_font.setWeight(QFont.Weight.DemiBold)
        sender_font.setPointSize(11)
        sender.setFont(sender_font)
        bubble_layout.addWidget(sender)

        self._message = QLabel()
        self._message.setObjectName("messageLabel")
        self._message.setWordWrap(True)
        self._message.setTextFormat(Qt.TextFormat.RichText)
        self._message.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self._message.setOpenExternalLinks(True)
        self._message.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        html_content = render_markdown(self.content, self._theme)
        self._message.setText(html_content)
        bubble_layout.addWidget(self._message)

        self._tool_container = QWidget()
        self._tool_layout = QVBoxLayout(self._tool_container)
        self._tool_layout.setContentsMargins(0, 4, 0, 0)
        self._tool_layout.setSpacing(6)
        bubble_layout.addWidget(self._tool_container)

        time_str = self.timestamp.strftime("%H:%M")
        time_label = QLabel(time_str)
        time_label.setObjectName("timeLabel")
        time_label.setProperty("muted", True)
        time_font = QFont()
        time_font.setPointSize(10)
        time_label.setFont(time_font)
        bubble_layout.addWidget(time_label)

        bubble.setMinimumWidth(100)
        bubble.setMaximumWidth(700)
        bubble.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum)

        outer_layout.addWidget(bubble)
        outer_layout.addStretch()

        self._apply_style(bubble, sender, self._message, time_label)

    def _apply_style(self, bubble: QFrame, sender: QLabel, message: QLabel, time_label: QLabel):
        if not self._theme:
            return

        bg = self._theme.ai_bubble
        text = self._theme.ai_text

        bubble.setStyleSheet(
            f"""
                QFrame#assistantTurn {{
                    background-color: {bg};
                    border-radius: 12px;
                }}
            """
        )

        sender.setStyleSheet(f"color: {text}; background: transparent;")
        message.setStyleSheet(f"color: {text}; background: transparent;")
        time_label.setStyleSheet(f"color: {self._theme.text_muted}; background: transparent;")

    def add_tool_call(self, tool_name: str, arguments: dict) -> ToolCallWidget:
        widget = ToolCallWidget(
            tool_name=tool_name,
            arguments=arguments,
            theme=self._theme,
            parent=self,
        )
        self._tool_layout.addWidget(widget)
        return widget

    def set_theme(self, theme: Theme):
        self._theme = theme
