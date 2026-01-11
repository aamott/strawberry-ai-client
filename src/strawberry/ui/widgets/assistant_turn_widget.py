"""Assistant turn widget."""
import re
from datetime import datetime
from typing import List, Optional, Tuple

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..markdown_renderer import render_markdown
from ..theme import Theme
from .auto_resizing_text_browser import AutoResizingTextBrowser


def _parse_chunks(md: str) -> List[Tuple[str, str, Optional[str]]]:
    """Parse markdown into text/code/output chunks.

    Returns tuples of:
    - ("text", text, None)
    - ("code", code, language)
    - ("output", output, None)
    """
    if not md:
        return [("text", "", None)]

    chunks: List[Tuple[str, str, Optional[str]]] = []
    pattern = re.compile(r"```(?P<lang>[A-Za-z0-9_-]+)?\n(?P<body>.*?)\n?```", re.DOTALL)

    last_end = 0
    for match in pattern.finditer(md):
        # Any text before this block
        if match.start() > last_end:
            text = md[last_end : match.start()]
            if text:
                chunks.append(("text", text, None))

        lang = match.group("lang")
        lang_norm = lang.lower() if lang else None
        body = (match.group("body") or "").strip()

        if lang_norm in ("output", "result"):
            chunks.append(("output", body, None))
        else:
            chunks.append(("code", body, lang_norm))

        last_end = match.end()

    # Trailing text
    if last_end < len(md):
        text = md[last_end:]
        if text:
            chunks.append(("text", text, None))

    if not chunks:
        return [("text", md, None)]

    # If the whole string was plain text, normalize to single chunk.
    if len(chunks) == 1 and chunks[0][0] == "text":
        return [("text", md, None)]

    return chunks


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
        self._message_view = AutoResizingTextBrowser()
        self._message_view.setObjectName("messageView")
        self._message_view.setFrameShape(QFrame.Shape.NoFrame)
        self._message_view.setOpenExternalLinks(True)
        self._message_view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        self._bubble_layout.addWidget(self._message_view)

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
        self._bubble.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        outer_layout.addWidget(self._bubble, 1)

        self._apply_style()

    def _render_message(self) -> None:
        """Render markdown content as HTML."""
        html_content = render_markdown(self._markdown or "", self._theme)
        self._message_view.setHtml(html_content)

        if self._theme:
            self._message_view.setStyleSheet(
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
