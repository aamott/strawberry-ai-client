"""Desktop UI for Strawberry AI Spoke."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import StrawberryApp
    from .main_window import MainWindow

__all__ = ["StrawberryApp", "MainWindow"]


def __getattr__(name: str):
    if name == "StrawberryApp":
        from .app import StrawberryApp as _StrawberryApp

        return _StrawberryApp
    if name == "MainWindow":
        from .main_window import MainWindow as _MainWindow

        return _MainWindow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

