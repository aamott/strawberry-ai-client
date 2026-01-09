"""Assistant turn widget (notebook-style).

Renders an assistant message with inline, collapsible code blocks and tool
call/output sections.
"""

import re
from datetime import datetime
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..markdown_renderer import render_markdown
from ..theme import Theme
from .code_block_widget import CodeBlockWidget
from .output_widget import OutputWidget
from .tool_call_widget import ToolCallWidget

# Regex pattern to find fenced code blocks: ```language\n...code...\n```
_CODE_BLOCK_PATTERN = re.compile(
    r"```(\w*)\s*\n(.*?)\n```",
    re.DOTALL,
)


def _parse_chunks(markdown: str) -> List[Tuple[str, Optional[str], Optional[str]]]:
    """Parse markdown into chunks of (type, content, language).

    Returns a list of tuples:
        - ("text", content, None) for plain markdown text
        - ("code", code, language) for code blocks
        - ("output", content, None) for output blocks (```output ... ```)

    This preserves the order of chunks as they appear in the markdown.
    """
    chunks = []
    last_end = 0

    for match in _CODE_BLOCK_PATTERN.finditer(markdown):
        # Text before this code block
        if match.start() > last_end:
            text_chunk = markdown[last_end : match.start()].strip()
            if text_chunk:
                chunks.append(("text", text_chunk, None))

        # The code/output block itself
        language = match.group(1).lower() or "python"  # Default to python
        content = match.group(2)

        if language in ("output", "result"):
            chunks.append(("output", content, None))
        else:
            chunks.append(("code", content, language))

        last_end = match.end()

    # Text after the last code block
    if last_end < len(markdown):
        text_chunk = markdown[last_end:].strip()
        if text_chunk:
            chunks.append(("text", text_chunk, None))

    # If no chunks found, treat entire content as text
    if not chunks and markdown.strip():
        chunks.append(("text", markdown.strip(), None))

    return chunks


class AssistantTurnWidget(QFrame):
    """Notebook-style assistant turn with collapsible code blocks."""

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
        self._content_widgets: List[QWidget] = []

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
        self._content_container = QWidget()
        self._content_layout = QVBoxLayout(self._content_container)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(6)
        self._bubble_layout.addWidget(self._content_container)

        # Render initial content
        self._render_message()

        # Tool calls container (after content) - kept for legacy/other tools
        self._tool_container = QWidget()
        self._tool_layout = QVBoxLayout(self._tool_container)
        self._tool_layout.setContentsMargins(0, 4, 0, 0)
        self._tool_layout.setSpacing(6)
        self._bubble_layout.addWidget(self._tool_container)

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

    def _clear_content_widgets(self):
        """Remove all content widgets (text labels and code blocks)."""
        for widget in self._content_widgets:
            self._content_layout.removeWidget(widget)
            widget.deleteLater()
        self._content_widgets.clear()

    def _render_message(self) -> None:
        """Parse markdown and render text/code/output chunks."""
        self._clear_content_widgets()

        if not self._markdown:
            return

        chunks = _parse_chunks(self._markdown)

        for chunk_type, content, language in chunks:
            if chunk_type == "text":
                # Render text as markdown → HTML in a QLabel
                label = QLabel()
                label.setObjectName("messageLabel")
                label.setWordWrap(True)
                label.setTextFormat(Qt.TextFormat.RichText)
                label.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                    | Qt.TextInteractionFlag.TextSelectableByKeyboard
                    | Qt.TextInteractionFlag.LinksAccessibleByMouse
                )
                label.setOpenExternalLinks(True)
                label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

                html_content = render_markdown(content, self._theme)
                label.setText(html_content)

                if self._theme:
                    label.setStyleSheet(
                        f"color: {self._theme.ai_text}; background: transparent;"
                    )

                self._content_layout.addWidget(label)
                self._content_widgets.append(label)

            elif chunk_type == "code":
                # Render code as collapsible CodeBlockWidget
                widget = CodeBlockWidget(
                    code=content,
                    language=language,
                    theme=self._theme,
                    parent=self._content_container,
                )
                self._content_layout.addWidget(widget)
                self._content_widgets.append(widget)

            elif chunk_type == "output":
                # Render output as OutputWidget
                widget = OutputWidget(
                    content=content,
                    theme=self._theme,
                    parent=self._content_container,
                )
                self._content_layout.addWidget(widget)
                self._content_widgets.append(widget)

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

    def add_tool_call(self, tool_name: str, arguments: dict) -> ToolCallWidget:
        """Add a tool call widget to this turn."""
        widget = ToolCallWidget(
            tool_name=tool_name,
            arguments=arguments,
            theme=self._theme,
            parent=self,
        )
        self._tool_layout.addWidget(widget)
        return widget

    def set_theme(self, theme: Theme):
        """Update the widget's theme."""
        self._theme = theme
        self._apply_style()
        self._render_message()
