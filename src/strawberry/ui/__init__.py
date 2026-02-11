"""UI modules for Strawberry AI.

Contains:
- qt/ - Qt-based graphical user interface
- cli/ - Command-line interface
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .qt import MainWindow, QtVoiceAdapter

__all__ = ["MainWindow", "QtVoiceAdapter"]


def __getattr__(name: str):
    """Lazy import to avoid circular dependencies."""
    if name == "MainWindow":
        from .qt import MainWindow as _MainWindow

        return _MainWindow
    if name == "QtVoiceAdapter":
        from .qt import QtVoiceAdapter as _QtVoiceAdapter

        return _QtVoiceAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
