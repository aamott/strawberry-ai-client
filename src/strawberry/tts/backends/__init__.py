"""TTS backend implementations."""

from .mock import MockTTS

__all__ = ["MockTTS"]


def get_orca_tts():
    """Get OrcaTTS class (requires pvorca)."""
    from .orca import OrcaTTS
    return OrcaTTS

