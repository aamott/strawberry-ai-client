"""Shared Qt widget subclasses used by both Qt and gui_v2 frontends.

These prevent accidental value changes when scrolling through settings pages.
"""

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QSpinBox


class NoScrollComboBox(QComboBox):
    """QComboBox that ignores wheel events unless explicitly focused.

    Prevents accidental value changes when scrolling through a settings page.
    """

    def wheelEvent(self, event: QEvent) -> None:  # noqa: N802
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class NoScrollSpinBox(QSpinBox):
    """QSpinBox that ignores wheel events unless explicitly focused."""

    def wheelEvent(self, event: QEvent) -> None:  # noqa: N802
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class NoScrollDoubleSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox that ignores wheel events unless explicitly focused."""

    def wheelEvent(self, event: QEvent) -> None:  # noqa: N802
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()
