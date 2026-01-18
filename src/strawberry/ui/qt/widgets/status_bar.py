"""Custom status bar widget."""

from typing import Optional

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from ..theme import Theme


class StatusIndicator(QFrame):
    """Small colored dot indicator."""

    def __init__(self, color: str = "#888888", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(8, 8)
        self.set_color(color)

    def set_color(self, color: str):
        """Set the indicator color."""
        self.setStyleSheet(f"""
            StatusIndicator {{
                background-color: {color};
                border-radius: 4px;
            }}
        """)


class StatusBar(QWidget):
    """Status bar showing connection status and info."""

    def __init__(self, theme: Optional[Theme] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._theme = theme
        self._setup_ui()

    def _setup_ui(self):
        """Set up the status bar."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 16, 6)
        layout.setSpacing(8)

        # Connection indicator
        self._indicator = StatusIndicator()
        layout.addWidget(self._indicator)

        # Status text
        self._status_label = QLabel("Disconnected")
        self._status_label.setProperty("muted", True)
        layout.addWidget(self._status_label)

        layout.addStretch()

        # Right side info
        self._info_label = QLabel("")
        self._info_label.setProperty("muted", True)
        layout.addWidget(self._info_label)

        # Apply theme
        if self._theme:
            self._apply_theme()

    def _apply_theme(self):
        """Apply theme styling."""
        if not self._theme:
            return

        self.setStyleSheet(f"""
            StatusBar {{
                background-color: {self._theme.bg_secondary};
                border-top: 1px solid {self._theme.border};
            }}
            QLabel {{
                color: {self._theme.text_muted};
                font-size: 12px;
                background: transparent;
            }}
        """)

    def set_connected(self, connected: bool, hub_url: str = ""):
        """Update connection status."""
        if connected:
            if self._theme:
                self._indicator.set_color(self._theme.success)
            else:
                self._indicator.set_color("#3fb950")
            self._status_label.setText(f"Connected to {hub_url}" if hub_url else "Connected")
        else:
            if self._theme:
                self._indicator.set_color(self._theme.text_muted)
            else:
                self._indicator.set_color("#888888")
            self._status_label.setText("Disconnected")

    def set_status(self, text: str):
        """Set status text."""
        self._status_label.setText(text)

    def set_info(self, text: str):
        """Set right-side info text."""
        self._info_label.setText(text)

    def set_theme(self, theme: Theme):
        """Update theme."""
        self._theme = theme
        self._apply_theme()

