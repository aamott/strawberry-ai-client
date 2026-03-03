"""Wake word backend implementations."""

from .mock import MockWakeWordDetector

__all__ = ["MockWakeWordDetector"]


# Conditional imports for heavy dependencies
def get_porcupine_detector():
    """Get PorcupineDetector class (requires pvporcupine)."""
    from .porcupine import PorcupineDetector

    return PorcupineDetector


def get_davoice_detector():
    """Get DaVoiceDetector class (requires keyword-detection-lib)."""
    from .davoice import DaVoiceDetector

    return DaVoiceDetector
