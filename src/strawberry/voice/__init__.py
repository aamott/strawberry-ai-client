"""Voice module for Strawberry AI.

Provides VoiceCore - a pure-Python voice processing engine that can be used
by any UI (CLI, VoiceInterface, etc.).

VoiceController is kept as an alias for backwards compatibility.
"""

from .state import VoiceState, VoiceStateError, can_transition
from .voice_core import (
    VoiceConfig,
    VoiceController,  # Backwards-compatible alias for VoiceCore
    VoiceCore,
    VoiceError,
    VoiceEvent,
    VoiceListening,
    VoiceResponse,
    VoiceSpeaking,
    VoiceStateChanged,
    VoiceStatusChanged,  # Backwards-compatible alias for VoiceStateChanged
    VoiceTranscription,
    VoiceWakeWordDetected,
)

__all__ = [
    # Core (primary)
    "VoiceCore",
    "VoiceConfig",
    # Backwards-compatible alias
    "VoiceController",
    # State
    "VoiceState",
    "VoiceStateError",
    "can_transition",
    # Events
    "VoiceEvent",
    "VoiceStateChanged",
    "VoiceStatusChanged",  # Alias for backwards compatibility
    "VoiceWakeWordDetected",
    "VoiceListening",
    "VoiceTranscription",
    "VoiceResponse",
    "VoiceSpeaking",
    "VoiceError",
]
