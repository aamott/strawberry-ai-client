"""Typing indicator component for GUI V2."""

from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget


class TypingIndicator(QWidget):
    """Animated typing indicator showing assistant is responding.

    Displays three dots that animate in sequence to indicate
    the assistant is processing/typing a response.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._dots = ["◉", "◉", "◉"]
        self._active_dot = 0
        self._timer: Optional[QTimer] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Initialize the UI."""
        self.setObjectName("TypingIndicator")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(32)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(4)

        # Add stretch to center the dots
        layout.addStretch()

        # Create dot labels
        self._dot_labels: list[QLabel] = []
        for i in range(3):
            label = QLabel(self._dots[i])
            label.setObjectName(f"Dot{i}")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._dot_labels.append(label)
            layout.addWidget(label)

        layout.addStretch()

        # Initially hidden
        self.hide()

    def _update_animation(self) -> None:
        """Update the dot animation state."""
        # Reset all dots to muted
        for label in self._dot_labels:
            label.setProperty("active", False)
            label.style().unpolish(label)
            label.style().polish(label)

        # Highlight active dot
        self._dot_labels[self._active_dot].setProperty("active", True)
        self._dot_labels[self._active_dot].style().unpolish(
            self._dot_labels[self._active_dot]
        )
        self._dot_labels[self._active_dot].style().polish(
            self._dot_labels[self._active_dot]
        )

        # Move to next dot
        self._active_dot = (self._active_dot + 1) % 3

    def start(self) -> None:
        """Start the typing animation and show the indicator."""
        self.show()

        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._update_animation)

        self._active_dot = 0
        self._update_animation()
        self._timer.start(400)  # 400ms between dot changes

    def stop(self) -> None:
        """Stop the typing animation and hide the indicator."""
        if self._timer:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None

        self.hide()

    @property
    def is_active(self) -> bool:
        """Check if the indicator is currently animating."""
        return self._timer is not None and self._timer.isActive()
