"""Widget for displaying tool outputs in chat (Integrated Notebook Style).

Displays execution results in a distinct, distinctively styled block.
"""

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..theme import Theme


class OutputWidget(QFrame):
    """Widget for displaying tool outputs."""

    def __init__(
        self,
        content: str,
        theme: Optional[Theme] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        self.content = content
        self._theme = theme

        self._setup_ui()
        self._apply_style()

    def _setup_ui(self):
        """Set up the widget UI."""
        self.setObjectName("outputWidget")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        # Header (Label)
        header = QHBoxLayout()
        header.setSpacing(6)

        icon_label = QLabel("⚡") # Or another icon like 📤 or ≡
        icon_label.setFixedWidth(20)
        header.addWidget(icon_label)

        title_label = QLabel("Output")
        title_label.setObjectName("outputTitle")
        title_label.setProperty("muted", True)
        header.addWidget(title_label)

        header.addStretch()
        layout.addLayout(header)

        # Content
        self._content_frame = QFrame()
        self._content_frame.setObjectName("outputContent")

        content_layout = QVBoxLayout(self._content_frame)
        content_layout.setContentsMargins(8, 8, 8, 8)

        self._text_label = QLabel(self.content)
        self._text_label.setObjectName("outputLabel")
        self._text_label.setWordWrap(True)
        self._text_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        # Monospace font for output, slightly smaller
        font = QFont("Consolas, Monaco, monospace")
        font.setPointSize(10)
        self._text_label.setFont(font)

        content_layout.addWidget(self._text_label)
        layout.addWidget(self._content_frame)

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

    def _apply_style(self):
        """Apply theme-based styling."""
        if not self._theme:
            return

        # Use transparent background for better integration
        text_muted = self._theme.text_muted

        self.setStyleSheet(f"""
            QFrame#outputWidget {{
                background-color: transparent;
                border: none;
            }}
            #outputTitle {{
                color: {text_muted};
                font-size: 11px;
                font-weight: bold;
                text-transform: uppercase;
            }}
            QFrame#outputContent {{
                background-color: transparent;
                border-left: 3px solid {self._theme.accent};
                border-radius: 4px;
                padding: 8px;
            }}
            #outputLabel {{
                color: {self._theme.text_primary};
                background: transparent;
            }}
        """)

    def set_theme(self, theme: Theme):
        """Update the widget's theme."""
        self._theme = theme
        self._apply_style()
