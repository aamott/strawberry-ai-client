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
    - Record button: trigger_wakeword (tap) and push-to-talk (hold)
    - Voice mode: toggle full pipeline (wakeword listening)
    - Converting VoiceEvents to Qt signals for UI updates

    Signals:
        state_changed: Emitted when voice state changes (str: old_state, str: new_state)
        wake_word_detected: Emitted when wake word is detected (str: keyword)
        listening_started: Emitted when listening for speech starts
        transcription_received: Emitted when speech is transcribed (str: text, bool: is_final)
        speaking_started: Emitted when TTS starts (str: text)
        speaking_finished: Emitted when TTS finishes
        error_occurred: Emitted on voice errors (str: error_message)
        voice_mode_changed: Emitted when voice mode is toggled (bool: active)
        availability_changed: Emitted when VoiceCore is set or cleared (bool: available)
        starting: Emitted when VoiceCore is about to be started (for UI "Starting..." state)
    """

    state_changed = Signal(str, str)  # old_state, new_state
    wake_word_detected = Signal(str)  # keyword
    listening_started = Signal()
    transcription_received = Signal(str, bool)  # text, is_final
    speaking_started = Signal(str)  # text
    speaking_finished = Signal()
    error_occurred = Signal(str)  # error message
    voice_mode_changed = Signal(bool)  # active
    availability_changed = Signal(bool)  # available
    starting = Signal()  # VoiceCore is being started

    def __init__(
        self,
        voice_core: Optional["VoiceCore"] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._voice = voice_core
        self._ptt_active = False
        self._voice_mode_active = False

    def set_voice_core(self, voice_core: "VoiceCore") -> None:
        """Set the VoiceCore instance and subscribe to events."""
        # Remove old listener if any
        if self._voice:
            self._voice.remove_listener(self._on_voice_event)

        self._voice = voice_core

        if self._voice:
            self._voice.add_listener(self._on_voice_event)

        # Notify UI that availability changed
        self.availability_changed.emit(self._voice is not None)

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

    # Shared helpers

    @property
    def is_available(self) -> bool:
        """Check if VoiceCore is set and usable."""
        return self._voice is not None

    async def _ensure_started(self, reason: str = "") -> bool:
        """Ensure VoiceCore is running, starting it if needed.

        Emits ``starting`` before the async start so the UI can show
        "Voice: Starting..." while initialization happens.

        Args:
            reason: Human-readable reason for the start (for logging).

        Returns:
            True if VoiceCore is running after this call.
        """
        if not self._voice:
            logger.warning("VoiceCore not set")
            self.error_occurred.emit("Voice engine not initialized")
            return False

        if self._voice.is_running():
            return True

        # Notify UI that we're starting
        logger.info("Starting VoiceCore%s", f" ({reason})" if reason else "")
        self.starting.emit()

        success = await self._voice.start()
        if not success:
            logger.error("Failed to start VoiceCore")
            self.error_occurred.emit("Failed to start voice engine")
            return False

        return True

    # Record button API (tap = trigger_wakeword, hold = PTT)

    async def trigger_wakeword(self) -> None:
        """Trigger immediate recording (skips wakeword detection).

        If VoiceCore is not running, starts it first so the audio pipeline
        is available, then triggers the wakeword to begin recording.
        VAD determines when to stop.
        """
        if not await self._ensure_started("record tap"):
            return

        self._voice.trigger_wakeword()
        logger.debug("Wakeword triggered (record tap)")

    async def push_to_talk_start(self) -> None:
        """Start push-to-talk recording (hold gesture).

        Auto-starts VoiceCore if not running.
        """
        if not await self._ensure_started("push-to-talk"):
            return

        self._ptt_active = True
        self._voice.push_to_talk_start()
        logger.debug("PTT started")

    def push_to_talk_stop(self) -> None:
        """Stop push-to-talk recording (release gesture)."""
        if not self._voice or not self._ptt_active:
            return

        self._ptt_active = False
        self._voice.push_to_talk_stop()
        logger.debug("PTT stopped")

    def is_push_to_talk_active(self) -> bool:
        """Check if push-to-talk is currently active."""
        return self._ptt_active

    # Voice Mode API (toggle full pipeline with wakeword listening)

    async def toggle_voice_mode(self, enabled: bool) -> None:
        """Toggle voice mode (full pipeline with wakeword detection).

        Args:
            enabled: True to start the voice pipeline, False to stop it.
        """
        if enabled:
            if not await self._ensure_started("voice mode"):
                # Reset the toggle so the UI doesn't stay in an incorrect state
                self.voice_mode_changed.emit(False)
                return
            self._voice_mode_active = True
            logger.info("Voice mode enabled (wakeword listening)")
        else:
            if not self._voice:
                self._voice_mode_active = False
                self.voice_mode_changed.emit(False)
                return
            if self._voice.is_running():
                await self._voice.stop()
            self._voice_mode_active = False
            logger.info("Voice mode disabled")

        self.voice_mode_changed.emit(self._voice_mode_active)

    @property
    def is_voice_mode_active(self) -> bool:
        """Check if voice mode (wakeword listening) is active."""
        return self._voice_mode_active

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

    @property
    def voice_mode_active(self) -> bool:
        """Check if voice mode is active."""
        return self._voice_mode_active
