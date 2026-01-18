"""Voice module for Strawberry AI.

Provides pure-Python voice controller that can be used by any UI.
"""

from .controller import (
    VoiceConfig,
    VoiceController,
    VoiceError,
    VoiceEvent,
    VoiceListening,
    VoiceResponse,
    VoiceSpeaking,
    VoiceStatusChanged,
    VoiceTranscription,
    VoiceWakeWordDetected,
)
from .state import VoiceState, VoiceStateError, can_transition

__all__ = [
    # Controller
    "VoiceController",
    "VoiceConfig",
    # State
    "VoiceState",
    "VoiceStateError",
    "can_transition",
    # Events
    "VoiceEvent",
    "VoiceStatusChanged",
    "VoiceWakeWordDetected",
    "VoiceListening",
    "VoiceTranscription",
    "VoiceResponse",
    "VoiceSpeaking",
    "VoiceError",
]
