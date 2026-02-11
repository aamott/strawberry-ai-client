"""Voice state machine for the voice controller."""

from enum import Enum, auto


class VoiceState(Enum):
    """States for the voice controller state machine.

    State transitions:
        STOPPED → IDLE (on start)
        IDLE → LISTENING (on wakeword or PTT)
        LISTENING → PROCESSING (on silence/end of speech)
        PROCESSING → SPEAKING (on TTS start) or IDLE (on skip TTS)
        SPEAKING → IDLE (on TTS complete)
        Any → STOPPED (on stop)
        Any → ERROR (on error, then → STOPPED)
    """

    STOPPED = auto()  # Voice is not running
    IDLE = auto()  # Waiting for wake word or PTT
    LISTENING = auto()  # Recording speech (VAD active)
    PROCESSING = auto()  # STT transcription + LLM response
    SPEAKING = auto()  # TTS playback
    ERROR = auto()  # Error state (transitional)


class VoiceStateError(Exception):
    """Exception raised for invalid state transitions."""

    def __init__(self, current: VoiceState, attempted: VoiceState):
        self.current = current
        self.attempted = attempted
        super().__init__(f"Invalid state transition: {current.name} → {attempted.name}")


# Valid state transitions
VALID_TRANSITIONS = {
    VoiceState.STOPPED: {VoiceState.IDLE},
    VoiceState.IDLE: {VoiceState.LISTENING, VoiceState.STOPPED, VoiceState.SPEAKING},
    VoiceState.LISTENING: {VoiceState.PROCESSING, VoiceState.IDLE, VoiceState.STOPPED},
    VoiceState.PROCESSING: {
        VoiceState.SPEAKING,
        VoiceState.IDLE,
        VoiceState.STOPPED,
        VoiceState.ERROR,
    },
    VoiceState.SPEAKING: {VoiceState.IDLE, VoiceState.STOPPED, VoiceState.LISTENING},
    VoiceState.ERROR: {VoiceState.STOPPED},
}


def can_transition(from_state: VoiceState, to_state: VoiceState) -> bool:
    """Check if a state transition is valid."""
    return to_state in VALID_TRANSITIONS.get(from_state, set())
