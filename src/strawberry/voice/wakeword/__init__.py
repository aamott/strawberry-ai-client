"""Wake word detection module for Strawberry AI."""

from .base import WakeWordDetector
from .discovery import discover_wake_modules, get_wake_module, list_wake_modules

__all__ = [
    "WakeWordDetector",
    "discover_wake_modules",
    "get_wake_module",
    "list_wake_modules",
]
