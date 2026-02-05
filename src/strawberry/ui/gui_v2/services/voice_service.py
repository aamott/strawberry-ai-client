"""Voice service - bridges VoiceCore to GUI V2."""

import logging
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from ....voice import VoiceCore

logger = logging.getLogger(__name__)


class VoiceService(QObject):
    """Service that bridges VoiceCore events to Qt signals.

    Handles:
    - Starting/stopping VoiceCore
    - Push-to-talk control
    - Converting VoiceEvents to Qt signals for UI updates

    Signals:
        state_changed: Emitted when voice state changes (str: old_state, str: new_state)
        wake_word_detected: Emitted when wake word is detected (str: keyword)
        listening_started: Emitted when listening for speech starts
        transcription_received: Emitted when speech is transcribed (str: text, bool: is_final)
        speaking_started: Emitted when TTS starts (str: text)
        speaking_finished: Emitted when TTS finishes
        error_occurred: Emitted on voice errors (str: error_message)
    """

    state_changed = Signal(str, str)  # old_state, new_state
    wake_word_detected = Signal(str)  # keyword
    listening_started = Signal()
    transcription_received = Signal(str, bool)  # text, is_final
    speaking_started = Signal(str)  # text
    speaking_finished = Signal()
    error_occurred = Signal(str)  # error message

    def __init__(
        self,
        voice_core: Optional["VoiceCore"] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._voice = voice_core
        self._ptt_active = False

    def set_voice_core(self, voice_core: "VoiceCore") -> None:
        """Set the VoiceCore instance and subscribe to events."""
        # Remove old listener if any
        if self._voice:
            self._voice.remove_listener(self._on_voice_event)

        self._voice = voice_core

        if self._voice:
            self._voice.add_listener(self._on_voice_event)

    def _on_voice_event(self, event) -> None:
        """Handle VoiceEvent and emit corresponding Qt signal."""
        from ....voice.events import (
            VoiceError,
            VoiceListening,
            VoiceSpeaking,
            VoiceStateChanged,
            VoiceTranscription,
            VoiceWakeWordDetected,
        )

        if isinstance(event, VoiceStateChanged):
            self.state_changed.emit(event.old_state.name, event.new_state.name)

        elif isinstance(event, VoiceWakeWordDetected):
            self.wake_word_detected.emit(event.keyword)

        elif isinstance(event, VoiceListening):
            self.listening_started.emit()

        elif isinstance(event, VoiceTranscription):
            self.transcription_received.emit(event.text, event.is_final)

        elif isinstance(event, VoiceSpeaking):
            self.speaking_started.emit(event.text)

        elif isinstance(event, VoiceError):
            self.error_occurred.emit(event.error)

    async def start(self) -> bool:
        """Start VoiceCore.

        Returns:
            True if started successfully.
        """
        if not self._voice:
            logger.warning("VoiceCore not set")
            return False
        return await self._voice.start()

    async def stop(self) -> None:
        """Stop VoiceCore."""
        if self._voice:
            await self._voice.stop()

    def is_running(self) -> bool:
        """Check if VoiceCore is running."""
        return self._voice.is_running() if self._voice else False

    def get_state(self) -> Optional[str]:
        """Get current voice state name."""
        if self._voice:
            return self._voice.get_state().name
        return None

    # Push-to-talk API

    def push_to_talk_start(self) -> None:
        """Start push-to-talk recording."""
        if not self._voice or not self._voice.is_running():
            logger.warning("VoiceCore not running")
            return

        self._ptt_active = True
        self._voice.push_to_talk_start()
        logger.debug("PTT started")

    def push_to_talk_stop(self) -> None:
        """Stop push-to-talk recording."""
        if not self._voice or not self._ptt_active:
            return

        self._ptt_active = False
        self._voice.push_to_talk_stop()
        logger.debug("PTT stopped")

    def is_push_to_talk_active(self) -> bool:
        """Check if push-to-talk is currently active."""
        return self._ptt_active

    # TTS API

    def speak(self, text: str) -> None:
        """Speak text using TTS.

        Args:
            text: Text to speak.
        """
        if not self._voice or not self._voice.is_running():
            logger.warning("VoiceCore not running")
            return

        self._voice.speak(text)

    def stop_speaking(self) -> None:
        """Stop current TTS playback."""
        if self._voice:
            self._voice.stop_speaking()

    @property
    def voice_core(self) -> Optional["VoiceCore"]:
        """Get the VoiceCore instance."""
        return self._voice
