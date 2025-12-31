"""VAD backend implementations."""

from .mock import MockVAD

__all__ = ["MockVAD"]

# Conditional imports for heavy dependencies
def get_silero_vad():
    """Get SileroVAD class (requires torch)."""
    from .silero import SileroVAD
    return SileroVAD

