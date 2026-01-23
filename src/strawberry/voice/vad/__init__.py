"""Voice Activity Detection module for Strawberry AI."""

from .base import VADBackend
from .discovery import discover_vad_modules, get_vad_module, list_vad_modules
from .processor import VADConfig, VADProcessor

__all__ = [
    "VADBackend",
    "VADProcessor",
    "VADConfig",
    "discover_vad_modules",
    "get_vad_module",
    "list_vad_modules",
]
