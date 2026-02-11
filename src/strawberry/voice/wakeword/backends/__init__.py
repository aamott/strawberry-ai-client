"""Wake word backend implementations."""

from .mock import MockWakeWordDetector

__all__ = ["MockWakeWordDetector"]


# Conditional imports for heavy dependencies
def get_porcupine_detector():
    """Get PorcupineDetector class (requires pvporcupine)."""
    from .porcupine import PorcupineDetector

    return PorcupineDetector
