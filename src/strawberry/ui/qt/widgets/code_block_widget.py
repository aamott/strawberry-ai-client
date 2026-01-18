"""Widget for displaying collapsible code blocks in chat (Phase 2).

Shows a collapsed summary by default (e.g., "Ran python code") that expands
to reveal the full code block when clicked.
"""

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..theme import Theme


class CodeBlockWidget(QFrame):
    """Collapsible code block widget.

    Default state: Collapsed (shows summary like "Ran python code").
    Click to expand: Shows the full code block.
    """

    toggled = Signal(bool)  # Emitted when expanded/collapsed

    def __init__(
        self,
        code: str,
        language: str = "python",
        summary: Optional[str] = None,
        theme: Optional[Theme] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        self.code = code
        self.language = language
        self._theme = theme
        self._expanded = False
        self._summary = summary or f"Ran {language} code"

        self._setup_ui()
        self._apply_style()

    def _setup_ui(self):
        """Set up the widget UI."""
        self.setObjectName("codeBlockWidget")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        # Header row (always visible)
        header = QHBoxLayout()
        header.setSpacing(8)

        # Code icon
        icon_label = QLabel("📄")
        icon_label.setFixedWidth(20)
        header.addWidget(icon_label)

        # Summary label
        self._summary_label = QLabel(self._summary)
        self._summary_label.setProperty("muted", True)
        header.addWidget(self._summary_label, 1)

        # Expand/collapse button
        self._expand_btn = QPushButton("▶")
        self._expand_btn.setObjectName("expandBtn")
        self._expand_btn.setFixedSize(24, 24)
        self._expand_btn.setToolTip("Show code")
        self._expand_btn.clicked.connect(self._toggle_expand)
        self._expand_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        header.addWidget(self._expand_btn)

        layout.addLayout(header)

        # Code content (hidden by default)
        self._code_frame = QFrame()
        self._code_frame.setObjectName("codeContent")
        self._code_frame.setVisible(False)

        code_layout = QVBoxLayout(self._code_frame)
        code_layout.setContentsMargins(0, 4, 0, 0)

        self._code_label = QLabel(self.code)
        self._code_label.setObjectName("codeLabel")
        self._code_label.setWordWrap(True)
        self._code_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        # Monospace font for code
        code_font = QFont("Consolas, Monaco, monospace")
        code_font.setPointSize(11)
        self._code_label.setFont(code_font)

        code_layout.addWidget(self._code_label)

        layout.addWidget(self._code_frame)

    def _apply_style(self):
        """Apply theme-based styling."""
        if not self._theme:
            return

        bg = self._theme.bg_tertiary
        border = self._theme.border
        text_muted = self._theme.text_muted
        code_bg = self._theme.bg_secondary

        self.setStyleSheet(f"""
            QFrame#codeBlockWidget {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 6px;
            }}
            #expandBtn {{
                background-color: transparent;
                border: none;
                font-size: 12px;
                color: {text_muted};
            }}
            #expandBtn:hover {{
                color: {self._theme.accent};
            }}
            QFrame#codeContent {{
                background-color: {code_bg};
                border-radius: 4px;
                padding: 8px;
            }}
            #codeLabel {{
                color: {self._theme.text_primary};
                background: transparent;
            }}
        """)

    def _toggle_expand(self):
        """Toggle expanded/collapsed state."""
        self._expanded = not self._expanded
        self._code_frame.setVisible(self._expanded)
        self._expand_btn.setText("▼" if self._expanded else "▶")
        self._expand_btn.setToolTip("Hide code" if self._expanded else "Show code")
        self.toggled.emit(self._expanded)

    def set_expanded(self, expanded: bool):
        """Set expanded state programmatically."""
        if expanded != self._expanded:
            self._toggle_expand()

    def is_expanded(self) -> bool:
        """Return current expanded state."""
        return self._expanded

    def set_theme(self, theme: Theme):
        """Update the widget's theme."""
        self._theme = theme
        self._apply_style()
