"""Voice module for Strawberry AI.

Provides VoiceCore - a pure-Python voice processing engine that can be used
by any UI (CLI, VoiceInterface, etc.).

VoiceController is kept as an alias for backwards compatibility.
"""

from .config import VoiceConfig
from .events import (
    VoiceError,
    VoiceEvent,
    VoiceListening,
    VoiceNoSpeechDetected,
    VoiceResponse,
    VoiceSpeaking,
    VoiceStateChanged,
    VoiceTranscription,
    VoiceWakeWordDetected,
)
from .state import VoiceState, VoiceStateError, can_transition
from .voice_core import (
    VoiceController,  # Backwards-compatible alias for VoiceCore
    VoiceCore,
    VoiceStatusChanged,  # Backwards-compatible alias for VoiceStateChanged
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
    "VoiceNoSpeechDetected",
    "VoiceTranscription",
    "VoiceResponse",
    "VoiceSpeaking",
    "VoiceError",
]
