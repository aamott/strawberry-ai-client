"""Listener finite state machine for voice pipeline.

Manages the listener lifecycle: IDLE -> LISTENING -> PROCESSING -> IDLE
"""

import logging
import threading
from enum import Enum, auto

logger = logging.getLogger(__name__)


class ListenerState(Enum):
    """States for the listener FSM."""

    IDLE = auto()  # Waiting for wakeword or PTT
    LISTENING = auto()  # Recording speech (VAD active)
    PROCESSING = auto()  # STT transcription in progress


# Valid listener state transitions
LISTENER_TRANSITIONS = {
    ListenerState.IDLE: {ListenerState.LISTENING},
    ListenerState.LISTENING: {ListenerState.PROCESSING, ListenerState.IDLE},
    ListenerState.PROCESSING: {ListenerState.IDLE},
}


class ListenerFSM:
    """Thread-safe finite state machine for the listener component.

    Handles state transitions for:
    - Wakeword detection -> start listening
    - VAD speech end -> start processing
    - Transcription complete -> return to idle
    """

    def __init__(self):
        self._state = ListenerState.IDLE
        self._lock = threading.Lock()
        self._state_change_callbacks: list = []

    @property
    def state(self) -> ListenerState:
        """Thread-safe state getter."""
        with self._lock:
            return self._state

    def add_state_change_callback(self, callback) -> None:
        """Add callback to be notified on state changes."""
        self._state_change_callbacks.append(callback)

    def _transition_to(self, new_state: ListenerState) -> bool:
        """
        Attempt state transition. Returns True if successful.

        Args:
            new_state: The target state to transition to.

        Returns:
            True if the transition was valid and executed, False otherwise.
        """
        with self._lock:
            old_state = self._state
            if new_state in LISTENER_TRANSITIONS.get(old_state, set()):
                self._state = new_state
                logger.info(f"Listener: {old_state.name} -> {new_state.name}")
                # Notify callbacks outside lock to avoid deadlocks
                callbacks = list(self._state_change_callbacks)
            else:
                logger.warning(
                    f"Listener: Invalid transition {old_state.name} -> {new_state.name}"
                )
                return False

        for cb in callbacks:
            try:
                cb(old_state, new_state)
            except Exception as e:
                logger.error(f"Listener state callback error: {e}")

        return True

    def start_listening(self) -> bool:
        """Transition to LISTENING state. Returns True if successful."""
        return self._transition_to(ListenerState.LISTENING)

    def start_processing(self) -> bool:
        """Transition to PROCESSING state. Returns True if successful."""
        return self._transition_to(ListenerState.PROCESSING)

    def finish(self) -> bool:
        """Transition to IDLE state. Returns True if successful."""
        return self._transition_to(ListenerState.IDLE)

    def reset(self) -> None:
        """Force reset to IDLE (used on stop/error)."""
        with self._lock:
            old_state = self._state
            self._state = ListenerState.IDLE
            if old_state != ListenerState.IDLE:
                logger.info(f"Listener: {old_state.name} -> IDLE (reset)")
