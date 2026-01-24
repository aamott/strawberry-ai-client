"""TTS backend implementations."""

from .mock import MockTTS

__all__ = ["MockTTS"]


def get_orca_tts():
    """Get OrcaTTS class (requires pvorca)."""
    from .orca import OrcaTTS

    return OrcaTTS


def get_pocket_tts():
    """Get PocketTTS class (requires pocket-tts)."""
    from .pocket import PocketTTS

    return PocketTTS


def get_soprano_tts():
    """Get SopranoTTS class (requires soprano-tts and CUDA GPU)."""
    from .soprano import SopranoTTS

    return SopranoTTS
