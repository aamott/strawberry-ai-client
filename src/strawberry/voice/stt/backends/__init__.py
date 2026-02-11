"""STT backend implementations."""

from .mock import MockSTT

__all__ = ["MockSTT"]


def get_leopard_stt():
    """Get LeopardSTT class (requires pvleopard)."""
    from .leopard import LeopardSTT

    return LeopardSTT
