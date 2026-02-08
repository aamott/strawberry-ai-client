"""Toast notification overlay — auto-dismissing, semi-transparent."""

from enum import Enum
from typing import Optional

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..utils.icons import Icons


class ToastLevel(Enum):
    """Severity level for toast notifications."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"


# Icon per level
_LEVEL_ICON = {
    ToastLevel.INFO: Icons.INFO,
    ToastLevel.WARNING: Icons.WARNING,
    ToastLevel.ERROR: Icons.ERROR,
    ToastLevel.SUCCESS: Icons.SUCCESS,
}


class _ToastCard(QFrame):
    """Single toast card that fades in, waits, then fades out."""

    def __init__(
        self,
        message: str,
        level: ToastLevel = ToastLevel.INFO,
        duration_ms: int = 3500,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setObjectName("ToastCard")
        self.setProperty("level", level.value)
        self._message = message

        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        top_layout = QHBoxLayout()
        layout.addLayout(top_layout)

        icon_label = QLabel(_LEVEL_ICON.get(level, ""))
        icon_label.setObjectName("ToastIcon")
        top_layout.addWidget(icon_label)

        text_label = QLabel(message)
        text_label.setObjectName("ToastText")
        text_label.setWordWrap(True)
        text_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        top_layout.addWidget(text_label, 1)

        # Copy button (top-right)
        copy_btn = QToolButton()
        copy_btn.setObjectName("ToastCopyButton")
        copy_btn.setText(Icons.COPY)
        copy_btn.setToolTip("Copy message")
        copy_btn.clicked.connect(self._copy_message)
        top_layout.addWidget(copy_btn)
        top_layout.setStretch(1, 1)

        self._duration_ms = duration_ms
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.adjustSize()

        # QGraphicsOpacityEffect for proper fade animation
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

    def show_animated(self) -> None:
        """Fade in, wait, then fade out and delete."""
        self.show()
        self.raise_()

        # Fade in
        fade_in = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        fade_in.setDuration(200)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade_in.start()
        self._fade_in = fade_in  # prevent GC

        # Schedule fade-out after duration
        QTimer.singleShot(self._duration_ms, self._fade_out)

    def _fade_out(self) -> None:
        """Fade out and delete self."""
        fade_out = QPropertyAnimation(
            self._opacity_effect, b"opacity", self,
        )
        fade_out.setDuration(300)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        fade_out.finished.connect(self._remove)
        fade_out.start()
        self._fade_out_anim = fade_out  # prevent GC

    def _remove(self) -> None:
        """Remove from parent and delete."""
        self.hide()
        self.deleteLater()

    def _copy_message(self) -> None:
        """Copy the toast message text to clipboard."""
        QGuiApplication.clipboard().setText(self._message)


class ToastManager:
    """Manages a stack of toast notifications anchored to a parent widget.

    Toasts appear at the top-center of the parent, stacking downward.
    Each toast auto-dismisses after its duration.

    Usage:
        toast_mgr = ToastManager(parent_widget)
        toast_mgr.show("Copied to clipboard", ToastLevel.SUCCESS)
        toast_mgr.show("Hub disconnected", ToastLevel.WARNING, duration_ms=5000)
    """

    # Vertical gap between stacked toasts
    _GAP = 6
    # Top offset from parent top
    _TOP_OFFSET = 8

    def __init__(self, parent: QWidget):
        self._parent = parent
        self._toasts: list[_ToastCard] = []

    def show(
        self,
        message: str,
        level: ToastLevel = ToastLevel.INFO,
        duration_ms: int = 3500,
    ) -> None:
        """Show a toast notification.

        Args:
            message: Text to display.
            level: Severity level (affects icon and color).
            duration_ms: How long the toast stays visible.
        """
        card = _ToastCard(message, level, duration_ms, parent=self._parent)
        card.setMinimumWidth(280)
        card.setMaximumWidth(420)
        card.adjustSize()

        self._toasts.append(card)
        self._reposition()
        card.show_animated()

        # Clean up reference when card is destroyed
        card.destroyed.connect(lambda: self._on_card_destroyed(card))

    def _on_card_destroyed(self, card: _ToastCard) -> None:
        """Remove destroyed card from the list and reposition."""
        if card in self._toasts:
            self._toasts.remove(card)
            self._reposition()

    def _reposition(self) -> None:
        """Reposition all visible toasts, stacking from top-center."""
        parent_w = self._parent.width()
        y = self._TOP_OFFSET

        for card in self._toasts:
            card_w = card.sizeHint().width()
            x = (parent_w - card_w) // 2
            card.move(x, y)
            y += card.height() + self._GAP
