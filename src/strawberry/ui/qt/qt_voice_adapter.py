"""Qt adapter for the pure-Python VoiceController.

This adapter wraps strawberry.voice.VoiceController or accepts an external
controller from SpokeCore, converting its events to Qt signals for thread-safe
UI updates.
"""

import asyncio
import logging
import threading
from typing import Callable, Optional, TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from ...audio.feedback import FeedbackSound, get_feedback
from ...voice import (
    VoiceConfig,
    VoiceController as CoreVoiceController,
    VoiceError,
    VoiceEvent,
    VoiceResponse,
    VoiceSpeaking,
    VoiceState,
    VoiceStatusChanged,
    VoiceTranscription,
    VoiceWakeWordDetected,
)

if TYPE_CHECKING:
    from ...config import Settings
    from ...core.app import SpokeCore

logger = logging.getLogger(__name__)


class QtVoiceAdapter(QObject):
    """Qt adapter for VoiceController.

    Can be used in two modes:
    1. Standalone: Creates its own VoiceController (legacy mode)
    2. SpokeCore: Attaches to SpokeCore's VoiceController for unified lifecycle

    Signals:
        state_changed(str): Voice state changed (idle, listening, processing, etc.)
        level_changed(float): Audio level changed (0.0 to 1.0)
        wake_word_detected(str): Wake word was detected
        transcription_ready(str): STT transcription is ready
        response_ready(str): LLM response is ready
        tts_started: TTS playback started
        tts_finished: TTS playback finished
        error_occurred(str): An error occurred
    """

    # Internal signals for thread-safe emission
    _emit_state = Signal(str)
    _emit_wake = Signal(str)
    _emit_transcription = Signal(str)
    _emit_response = Signal(str)
    _emit_tts_started = Signal()
    _emit_tts_finished = Signal()
    _emit_error = Signal(str)

    # Public signals
    state_changed = Signal(str)
    level_changed = Signal(float)
    wake_word_detected = Signal(str)
    transcription_ready = Signal(str)
    response_ready = Signal(str)
    tts_started = Signal()
    tts_finished = Signal()
    error_occurred = Signal(str)

    def __init__(
        self,
        settings: Optional["Settings"] = None,
        core: Optional["SpokeCore"] = None,
        response_handler: Optional[Callable[[str], str]] = None,
        parent: Optional[QObject] = None,
    ):
        """Initialize the Qt voice adapter.

        Args:
            settings: Settings object (for standalone mode). If core is provided,
                      settings are read from core instead.
            core: Optional SpokeCore instance. If provided, uses SpokeCore's
                  voice controller instead of creating a new one.
            response_handler: Callback for processing transcriptions.
            parent: Qt parent object.
        """
        super().__init__(parent)

        self._core = core
        self._settings = settings
        self._response_handler = response_handler
        self._running = False
        self._current_state = "stopped"
        self._main_thread_id = threading.get_ident()
        self._push_to_talk_active = False

        # Controller can be external (from SpokeCore) or internal (created here)
        self._controller: Optional[CoreVoiceController] = None
        self._owns_controller = False  # True if we created the controller

        # Audio feedback - use settings from core if available
        feedback_enabled = True
        if core and hasattr(core, '_settings'):
            feedback_enabled = core._settings.voice.audio_feedback_enabled
        elif settings:
            feedback_enabled = settings.voice.audio_feedback_enabled
        self._audio_feedback = get_feedback(enabled=feedback_enabled)

        # Timer for audio level updates (placeholder)
        self._level_timer = QTimer(self)
        self._level_timer.timeout.connect(self._update_level)

        # Connect internal signals to public signals (auto-queued for thread safety)
        self._emit_state.connect(
            self.state_changed.emit,
            Qt.ConnectionType.QueuedConnection,
        )
        self._emit_wake.connect(
            self.wake_word_detected.emit,
            Qt.ConnectionType.QueuedConnection,
        )
        self._emit_transcription.connect(
            self.transcription_ready.emit,
            Qt.ConnectionType.QueuedConnection,
        )
        self._emit_response.connect(
            self.response_ready.emit,
            Qt.ConnectionType.QueuedConnection,
        )
        self._emit_tts_started.connect(
            self.tts_started.emit,
            Qt.ConnectionType.QueuedConnection,
        )
        self._emit_tts_finished.connect(
            self.tts_finished.emit,
            Qt.ConnectionType.QueuedConnection,
        )
        self._emit_error.connect(
            self.error_occurred.emit,
            Qt.ConnectionType.QueuedConnection,
        )

    def set_response_handler(self, handler: Callable[[str], str]):
        """Set the response handler for processing transcriptions."""
        self._response_handler = handler
        if self._controller:
            self._controller.set_response_handler(handler)

    def start(self) -> bool:
        """Start voice interaction.

        In SpokeCore mode, starts voice via SpokeCore.
        In standalone mode, creates and starts its own controller.

        Returns:
            True if started successfully, False otherwise
        """
        if self._running:
            return True

        try:
            if self._core:
                # Use SpokeCore to manage voice lifecycle
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._start_via_core())
                else:
                    asyncio.run(self._start_via_core())
            else:
                # Standalone mode: create our own controller
                self._start_standalone()

            self._running = True
            self._level_timer.start(50)  # 20 FPS for level updates

            # Play start sound
            self._audio_feedback.play(FeedbackSound.LISTENING_START)

            logger.info("QtVoiceAdapter started")
            return True

        except Exception as e:
            logger.error(f"Failed to start voice: {e}")
            self._emit_error.emit(str(e))
            return False

    async def _start_via_core(self):
        """Start voice using SpokeCore."""
        await self._core.start_voice()

        # Get the controller from SpokeCore and subscribe to its events
        self._controller = self._core._voice
        self._owns_controller = False

        if self._controller:
            self._controller.add_listener(self._on_voice_event)
            if self._response_handler:
                self._controller.set_response_handler(self._response_handler)

    def _start_standalone(self):
        """Start voice in standalone mode (creates own controller)."""
        # Get settings from stored settings or use defaults
        settings = self._settings
        if not settings:
            from ...config import get_settings
            settings = get_settings()

        # Create voice config from settings
        config = VoiceConfig(
            wake_words=settings.wake.keywords or ["strawberry"],
            sensitivity=getattr(settings.wake, 'sensitivity', 0.5),
            sample_rate=16000,
        )

        # Create controller
        self._controller = CoreVoiceController(
            config=config,
            response_handler=self._response_handler,
        )
        self._owns_controller = True

        # Subscribe to events
        self._controller.add_listener(self._on_voice_event)

        # Start controller (run in event loop)
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(self._controller.start())
        else:
            asyncio.run(self._controller.start())

    def stop(self):
        """Stop voice interaction."""
        if not self._running:
            return

        self._running = False
        self._level_timer.stop()

        if self._controller:
            # Remove our listener
            self._controller.remove_listener(self._on_voice_event)

            # Only stop the controller if we own it
            if self._owns_controller:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._controller.stop())
                else:
                    asyncio.run(self._controller.stop())
            elif self._core:
                # Stop via SpokeCore
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._core.stop_voice())
                else:
                    asyncio.run(self._core.stop_voice())

            self._controller = None

        # Play stop sound
        self._audio_feedback.play(FeedbackSound.LISTENING_STOP)

        self._emit_state.emit("stopped")
        logger.info("QtVoiceAdapter stopped")

    def is_running(self) -> bool:
        """Check if voice is running."""
        return self._running

    @property
    def current_state(self) -> str:
        """Get the current voice state as a string."""
        return self._current_state

    def push_to_talk_start(self):
        """Start push-to-talk recording."""
        if not self._controller or not self._running:
            logger.warning("Cannot start PTT: controller not running")
            return

        if self._push_to_talk_active:
            return

        self._push_to_talk_active = True
        self._audio_feedback.play(FeedbackSound.PTT_START)

        # Start PTT (run in event loop)
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(self._controller.push_to_talk_start())

    def push_to_talk_stop(self):
        """Stop push-to-talk recording and process."""
        if not self._controller or not self._push_to_talk_active:
            return

        self._push_to_talk_active = False
        self._audio_feedback.play(FeedbackSound.PTT_STOP)

        # Stop PTT (run in event loop)
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(self._controller.push_to_talk_stop())

    def is_push_to_talk_active(self) -> bool:
        """Check if push-to-talk is currently active."""
        return self._push_to_talk_active

    def set_audio_feedback_enabled(self, enabled: bool):
        """Enable or disable audio feedback."""
        self._audio_feedback = get_feedback(enabled=enabled)

    def _on_voice_event(self, event: VoiceEvent):
        """Handle events from VoiceController and emit Qt signals."""
        if isinstance(event, VoiceStatusChanged):
            # Map VoiceState to lowercase string for compatibility
            state_map = {
                VoiceState.STOPPED: "stopped",
                VoiceState.IDLE: "idle",
                VoiceState.LISTENING: "listening",
                VoiceState.PROCESSING: "processing",
                VoiceState.SPEAKING: "speaking",
                VoiceState.ERROR: "error",
            }
            state_str = state_map.get(event.state, "idle")
            self._current_state = state_str
            self._emit_state.emit(state_str)

            # Play audio feedback based on state
            if event.state == VoiceState.LISTENING:
                self._audio_feedback.play(FeedbackSound.WAKE_DETECTED)
            elif event.state == VoiceState.PROCESSING:
                self._audio_feedback.play(FeedbackSound.PROCESSING)

        elif isinstance(event, VoiceWakeWordDetected):
            self._emit_wake.emit(event.keyword)
            self._audio_feedback.play(FeedbackSound.WAKE_DETECTED)

        elif isinstance(event, VoiceTranscription):
            if event.is_final:
                self._emit_transcription.emit(event.text)

        elif isinstance(event, VoiceResponse):
            self._emit_response.emit(event.text)

        elif isinstance(event, VoiceSpeaking):
            self._emit_tts_started.emit()

        elif isinstance(event, VoiceError):
            self._emit_error.emit(event.error)

    def _update_level(self):
        """Update audio level from pipeline."""
        # Placeholder - would get actual level from audio stream
        # For now, emit 0 when idle, random when listening
        if self._current_state == "listening":
            import random
            self.level_changed.emit(random.uniform(0.1, 0.5))
        else:
            self.level_changed.emit(0.0)


# Backward compatibility alias
VoiceController = QtVoiceAdapter
