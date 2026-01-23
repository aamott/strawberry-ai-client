"""Speech-to-Text module for Strawberry AI."""

from .base import STTEngine, TranscriptionResult
from .discovery import discover_stt_modules, get_stt_module, list_stt_modules

__all__ = [
    "STTEngine",
    "TranscriptionResult",
    "discover_stt_modules",
    "get_stt_module",
    "list_stt_modules",
]
