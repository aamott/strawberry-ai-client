"""Speaker finite state machine for voice pipeline.

Manages the speaker lifecycle: IDLE -> SPEAKING -> IDLE
with interrupt handling: SPEAKING -> INTERRUPTED -> IDLE/SPEAKING
"""

import logging
import threading
from enum import Enum, auto
from typing import List, Optional

logger = logging.getLogger(__name__)


class SpeakerState(Enum):
    """States for the speaker FSM."""

    IDLE = auto()        # No speech queued or playing
    SPEAKING = auto()    # TTS playback in progress
    INTERRUPTED = auto() # Playback stopped, pending speech buffered


# Valid speaker state transitions
SPEAKER_TRANSITIONS = {
    SpeakerState.IDLE: {SpeakerState.SPEAKING},
    SpeakerState.SPEAKING: {SpeakerState.IDLE, SpeakerState.INTERRUPTED},
    SpeakerState.INTERRUPTED: {SpeakerState.IDLE, SpeakerState.SPEAKING},
}


class SpeakerFSM:
    """Thread-safe finite state machine for the speaker component.

    Handles state transitions for:
    - New speech queued -> start speaking
    - Playback complete -> return to idle
    - Wakeword barge-in -> interrupt and buffer
    - Resume after no-speech -> continue buffered speech
    """

    def __init__(self):
        self._state = SpeakerState.IDLE
        self._lock = threading.Lock()
        self._buffer: List[str] = []
        self._current_text: Optional[str] = None
        self._state_change_callbacks: list = []

    @property
    def state(self) -> SpeakerState:
        """Thread-safe state getter."""
        with self._lock:
            return self._state

    @property
    def current_text(self) -> Optional[str]:
        """Get the current speech text being played."""
        with self._lock:
            return self._current_text

    @property
    def has_buffered_speech(self) -> bool:
        """Check if there's buffered speech to resume."""
        with self._lock:
            return len(self._buffer) > 0

    def add_state_change_callback(self, callback) -> None:
        """Add callback to be notified on state changes."""
        self._state_change_callbacks.append(callback)

    def _transition_to(self, new_state: SpeakerState) -> bool:
        """
        Attempt state transition. Returns True if successful.

        Args:
            new_state: The target state to transition to.

        Returns:
            True if the transition was valid and executed, False otherwise.
        """
        with self._lock:
            old_state = self._state
            if new_state in SPEAKER_TRANSITIONS.get(old_state, set()):
                self._state = new_state
                logger.info(f"Speaker: {old_state.name} -> {new_state.name}")
                callbacks = list(self._state_change_callbacks)
            else:
                logger.warning(
                    f"Speaker: Invalid transition {old_state.name} -> {new_state.name}"
                )
                return False

        for cb in callbacks:
            try:
                cb(old_state, new_state)
            except Exception as e:
                logger.error(f"Speaker state callback error: {e}")

        return True

    def start_speaking(self, text: str) -> bool:
        """
        Transition to SPEAKING state with the given text.

        Args:
            text: The text being spoken.

        Returns:
            True if transition successful.
        """
        with self._lock:
            old_state = self._state
            if SpeakerState.SPEAKING in SPEAKER_TRANSITIONS.get(old_state, set()):
                self._state = SpeakerState.SPEAKING
                self._current_text = text
                logger.info(f"Speaker: {old_state.name} -> SPEAKING")
                callbacks = list(self._state_change_callbacks)
            else:
                logger.warning(
                    f"Speaker: Invalid transition {old_state.name} -> SPEAKING"
                )
                return False

        for cb in callbacks:
            try:
                cb(old_state, SpeakerState.SPEAKING)
            except Exception as e:
                logger.error(f"Speaker state callback error: {e}")

        return True

    def finish_speaking(self) -> bool:
        """Transition to IDLE state after playback complete."""
        with self._lock:
            self._current_text = None
        return self._transition_to(SpeakerState.IDLE)

    def interrupt(self, pending_texts: Optional[List[str]] = None) -> bool:
        """
        Interrupt current playback and buffer pending speech.

        Args:
            pending_texts: Additional texts to buffer (from speak queue).

        Returns:
            True if interrupt successful.
        """
        with self._lock:
            old_state = self._state
            if old_state != SpeakerState.SPEAKING:
                logger.debug(f"Speaker: Cannot interrupt from {old_state.name}")
                return False

            # Buffer current text
            if self._current_text:
                self._buffer.append(self._current_text)
                logger.debug(f"Speaker: Buffered current: {self._current_text[:50]}...")

            # Buffer any additional pending texts
            if pending_texts:
                self._buffer.extend(pending_texts)
                logger.debug(f"Speaker: Buffered {len(pending_texts)} pending items")

            self._current_text = None
            self._state = SpeakerState.INTERRUPTED
            logger.info(
                f"Speaker: SPEAKING -> INTERRUPTED (buffer: {len(self._buffer)} items)"
            )
            callbacks = list(self._state_change_callbacks)

        for cb in callbacks:
            try:
                cb(old_state, SpeakerState.INTERRUPTED)
            except Exception as e:
                logger.error(f"Speaker state callback error: {e}")

        return True

    def get_buffered_speech(self) -> List[str]:
        """
        Get and clear buffered speech for resumption.

        Returns:
            List of buffered texts to speak.
        """
        with self._lock:
            buffered = list(self._buffer)
            self._buffer.clear()
            if buffered:
                logger.info(f"Speaker: Retrieved {len(buffered)} buffered items")
            return buffered

    def clear_buffer(self) -> None:
        """Clear buffered speech (user spoke something new)."""
        with self._lock:
            if self._buffer:
                logger.info(
                    f"Speaker: Clearing buffer ({len(self._buffer)} items discarded)"
                )
                self._buffer.clear()

            # If interrupted, transition to idle since buffer is now empty
            if self._state == SpeakerState.INTERRUPTED:
                self._state = SpeakerState.IDLE
                logger.info("Speaker: INTERRUPTED -> IDLE (buffer cleared)")

    def reset(self) -> None:
        """Force reset to IDLE (used on stop/error)."""
        with self._lock:
            old_state = self._state
            self._state = SpeakerState.IDLE
            self._current_text = None
            self._buffer.clear()
            if old_state != SpeakerState.IDLE:
                logger.info(f"Speaker: {old_state.name} -> IDLE (reset)")
