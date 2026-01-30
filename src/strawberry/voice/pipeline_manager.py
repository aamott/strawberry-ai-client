"""Voice pipeline manager - coordinates listener and speaker FSMs.

This module provides the central coordinator for the voice pipeline,
managing the interaction between the listener and speaker state machines.
"""

import logging
import threading
from typing import Callable, List, Optional

from .listener_fsm import ListenerFSM, ListenerState
from .speaker_fsm import SpeakerFSM, SpeakerState
from .state import VoiceState

logger = logging.getLogger(__name__)


class VoicePipelineManager:
    """Coordinates listener and speaker state machines.

    This manager:
    - Owns both FSMs and coordinates their interactions
    - Exposes a combined pipeline_state for external callers
    - Handles interrupt logic (wakeword during speaking)
    - Decides when to clear vs resume buffered speech
    """

    def __init__(self):
        self._listener = ListenerFSM()
        self._speaker = SpeakerFSM()
        self._lock = threading.Lock()
        self._stopped = True
        self._pipeline_state_callbacks: list = []

        # Wire up FSM callbacks for combined state updates
        self._listener.add_state_change_callback(self._on_listener_state_change)
        self._speaker.add_state_change_callback(self._on_speaker_state_change)

    @property
    def listener(self) -> ListenerFSM:
        """Access the listener FSM."""
        return self._listener

    @property
    def speaker(self) -> SpeakerFSM:
        """Access the speaker FSM."""
        return self._speaker

    @property
    def pipeline_state(self) -> VoiceState:
        """
        Get the combined pipeline state for external callers.

        Maps the dual FSM states to the legacy VoiceState enum:
        - STOPPED if pipeline is stopped
        - LISTENING if listener is listening
        - PROCESSING if listener is processing
        - SPEAKING if speaker is speaking and listener is idle
        - IDLE otherwise
        """
        with self._lock:
            if self._stopped:
                return VoiceState.STOPPED

            listener_state = self._listener.state
            speaker_state = self._speaker.state

            # Listener states take priority
            if listener_state == ListenerState.LISTENING:
                return VoiceState.LISTENING
            if listener_state == ListenerState.PROCESSING:
                return VoiceState.PROCESSING

            # Speaker states when listener is idle
            if speaker_state == SpeakerState.SPEAKING:
                return VoiceState.SPEAKING

            return VoiceState.IDLE

    @property
    def is_running(self) -> bool:
        """Check if the pipeline is running."""
        with self._lock:
            return not self._stopped

    def add_pipeline_state_callback(
        self, callback: Callable[[VoiceState, VoiceState], None]
    ) -> None:
        """Add callback for pipeline state changes."""
        self._pipeline_state_callbacks.append(callback)

    def _on_listener_state_change(
        self, old: ListenerState, new: ListenerState
    ) -> None:
        """Handle listener state changes and notify pipeline callbacks."""
        self._notify_pipeline_state_change()

    def _on_speaker_state_change(self, old: SpeakerState, new: SpeakerState) -> None:
        """Handle speaker state changes and notify pipeline callbacks."""
        self._notify_pipeline_state_change()

    def _notify_pipeline_state_change(self) -> None:
        """Notify callbacks of pipeline state change."""
        current = self.pipeline_state
        for cb in self._pipeline_state_callbacks:
            try:
                cb(current, current)  # We don't track old state here
            except Exception as e:
                logger.error(f"Pipeline state callback error: {e}")

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def start(self) -> None:
        """Start the pipeline."""
        with self._lock:
            self._stopped = False
            logger.info("Pipeline: Started")

    def stop(self) -> None:
        """Stop the pipeline and reset both FSMs."""
        with self._lock:
            self._stopped = True
        self._listener.reset()
        self._speaker.reset()
        logger.info("Pipeline: Stopped")

    # -------------------------------------------------------------------------
    # Wakeword / Interrupt Handling
    # -------------------------------------------------------------------------

    def on_wakeword_detected(
        self, pending_queue_items: Optional[List[str]] = None
    ) -> bool:
        """
        Handle wakeword detection.

        If speaking, interrupts and buffers pending speech.
        Transitions listener to LISTENING.

        Args:
            pending_queue_items: Items from speak queue to buffer on interrupt.

        Returns:
            True if successfully transitioned to listening.
        """
        with self._lock:
            if self._stopped:
                return False

        speaker_state = self._speaker.state

        # If speaking, interrupt first
        if speaker_state == SpeakerState.SPEAKING:
            logger.info("Pipeline: Wakeword during speaking - interrupting")
            self._speaker.interrupt(pending_queue_items)

        # Start listening
        return self._listener.start_listening()

    # -------------------------------------------------------------------------
    # Speech Processing Flow
    # -------------------------------------------------------------------------

    def on_speech_end(self) -> bool:
        """
        Handle end of speech detection (VAD).

        Transitions listener from LISTENING to PROCESSING.

        Returns:
            True if successfully transitioned.
        """
        return self._listener.start_processing()

    def on_no_speech_detected(self) -> bool:
        """
        Handle case where no speech was detected.

        Transitions listener to IDLE and checks if we should resume.

        Returns:
            True if there's buffered speech to resume.
        """
        self._listener.finish()
        return self._speaker.has_buffered_speech

    def on_transcription_complete(self, has_valid_text: bool) -> List[str]:
        """
        Handle transcription completion.

        Args:
            has_valid_text: Whether transcription produced valid text.

        Returns:
            List of buffered texts to resume (empty if valid text received).
        """
        self._listener.finish()

        if has_valid_text:
            # User spoke something new - clear old buffer
            self._speaker.clear_buffer()
            return []
        else:
            # No valid speech - resume buffered speech
            return self._speaker.get_buffered_speech()

    # -------------------------------------------------------------------------
    # Speaking
    # -------------------------------------------------------------------------

    def start_speaking(self, text: str) -> bool:
        """
        Start speaking the given text.

        Args:
            text: The text to speak.

        Returns:
            True if successfully transitioned to speaking.
        """
        with self._lock:
            if self._stopped:
                return False

            # Don't start speaking if we're listening
            if self._listener.state == ListenerState.LISTENING:
                logger.info("Pipeline: Deferring speech while listening")
                # Buffer the text for later
                self._speaker._buffer.append(text)
                return False

        return self._speaker.start_speaking(text)

    def finish_speaking(self) -> bool:
        """Finish speaking and transition to idle."""
        return self._speaker.finish_speaking()

    def can_speak(self) -> bool:
        """Check if it's safe to speak (not stopped, not listening)."""
        with self._lock:
            if self._stopped:
                return False
            return self._listener.state != ListenerState.LISTENING
