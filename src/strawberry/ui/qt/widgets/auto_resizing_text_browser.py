"""Auto-resizing QTextBrowser for chat bubbles.

QTextBrowser is a good fit for selectable rich text, but it defaults to a
scrollable viewport. For chat bubbles we want the widget to grow vertically to
fit its document (no internal vertical scrolling).
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import QTextBrowser


class AutoResizingTextBrowser(QTextBrowser):
    """A QTextBrowser that adjusts its height to fit its contents."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Update height when content changes.
        self.document().contentsChanged.connect(self._update_height)

    def event(self, event: QEvent) -> bool:
        # When width changes, Qt may reflow lines; recompute the height.
        if event.type() in (QEvent.Type.Resize, QEvent.Type.LayoutRequest):
            self._update_height()
        return super().event(event)

    def sizeHint(self) -> QSize:
        # Ensure parent layouts see a height that matches content.
        self._update_height()
        return super().sizeHint()

    def _update_height(self) -> None:
        doc = self.document()

        # Match text width to the available viewport width so wrapping is correct.
        # Guard against a 0-width viewport during early layout.
        viewport_width = max(1, self.viewport().width())
        doc.setTextWidth(viewport_width)

        # documentLayout().documentSize() is in layout units (pixels for Qt)
        doc_height = doc.documentLayout().documentSize().height()

        # Account for frame and margins.
        margins = self.contentsMargins()
        extra = self.frameWidth() * 2 + margins.top() + margins.bottom()

        self.setFixedHeight(int(doc_height + extra))
