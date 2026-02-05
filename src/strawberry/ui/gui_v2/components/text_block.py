"""Text block component for rendering markdown content."""

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QSizePolicy, QTextBrowser

# Import markdown renderer from existing Qt UI if available
try:
    from ...qt.markdown_renderer import markdown_to_html
except ImportError:
    # Fallback: basic markdown conversion
    import re

    def markdown_to_html(text: str) -> str:
        """Basic markdown to HTML conversion."""
        # Bold
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
        # Italic
        text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
        text = re.sub(r'_(.+?)_', r'<i>\1</i>', text)
        # Code
        text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
        # Links
        text = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', text)
        # Line breaks
        text = text.replace('\n', '<br>')
        return text


class TextBlock(QTextBrowser):
    """Markdown-rendered text block using QTextDocument.

    Renders markdown content with proper styling. This widget auto-sizes
    to fit its content and has no visible frame or scrollbars.

    Signals:
        content_changed: Emitted when content is updated
        height_changed: Emitted when the widget height changes
    """

    content_changed = Signal()
    height_changed = Signal(int)

    def __init__(self, content: str = "", parent: Optional[QFrame] = None):
        super().__init__(parent)
        self._content = content
        self._setup_ui()
        if content:
            self.set_content(content)

    def _setup_ui(self) -> None:
        """Initialize the UI."""
        self.setObjectName("TextBlock")
        self.setOpenExternalLinks(True)
        self.setReadOnly(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Size policy: expand horizontally, fit content vertically
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        # Connect document changes to height adjustment
        self.document().contentsChanged.connect(self._adjust_height)

    def _adjust_height(self) -> None:
        """Adjust widget height to fit content."""
        # Get the document's ideal height
        doc = self.document()
        doc.setTextWidth(self.viewport().width())
        doc_height = int(doc.size().height())

        # Add a small margin
        new_height = doc_height + 4

        if self.minimumHeight() != new_height:
            self.setMinimumHeight(new_height)
            self.setMaximumHeight(new_height)
            self.height_changed.emit(new_height)

    def resizeEvent(self, event) -> None:
        """Handle resize to recalculate height."""
        super().resizeEvent(event)
        self._adjust_height()

    def set_content(self, content: str) -> None:
        """Set markdown content.

        Args:
            content: Markdown text to render
        """
        self._content = content
        html = markdown_to_html(content)
        self.setHtml(html)
        self.content_changed.emit()

    def append_content(self, content: str) -> None:
        """Append content (for streaming).

        Args:
            content: Additional markdown text to append
        """
        self._content += content
        self.set_content(self._content)

    def get_content(self) -> str:
        """Get the raw markdown content."""
        return self._content

    def clear_content(self) -> None:
        """Clear all content."""
        self._content = ""
        self.clear()
        self.content_changed.emit()
