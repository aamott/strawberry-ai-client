"""Text-to-Speech module for Strawberry AI."""

from .base import AudioChunk, TTSEngine
from .discovery import discover_tts_modules, get_tts_module, list_tts_modules

__all__ = [
    "TTSEngine",
    "AudioChunk",
    "discover_tts_modules",
    "get_tts_module",
    "list_tts_modules",
]
