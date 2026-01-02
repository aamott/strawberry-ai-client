"""Voice controller for integrating audio pipeline with UI."""

import logging
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from ..audio.feedback import FeedbackSound, get_feedback
from ..config import Settings
from ..pipeline.events import EventType, PipelineEvent

logger = logging.getLogger(__name__)


@dataclass
class VoiceConfig:
    """Configuration for voice controller."""
    wake_words: list[str]
    sensitivity: float = 0.5
    sample_rate: int = 16000


class VoiceController(QObject):
    """Controller for voice interaction.

    Manages the conversation pipeline and emits Qt signals for UI updates.
    Uses thread-safe signal emission for cross-thread communication.

    Signals:
        state_changed(str): Voice state changed (idle, listening, recording, etc.)
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
        settings: Settings,
        response_handler: Optional[Callable[[str], str]] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)

        self.settings = settings
        self._response_handler = response_handler
        self._pipeline = None
        self._running = False
        self._current_state = "idle"
        self._main_thread_id = threading.get_ident()
        self._push_to_talk_active = False

        # Audio feedback
        self._audio_feedback = get_feedback(
            enabled=settings.voice.audio_feedback_enabled
        )

        # Timer created on main thread
        self._level_timer = QTimer(self)
        self._level_timer.timeout.connect(self._update_level)

        # Connect internal signals to public signals (auto-queued)
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

    def start(self) -> bool:
        """Start voice interaction.

        Returns:
            True if started successfully, False otherwise
        """
        if self._running:
            return True

        try:
            # Import voice components
            from ..audio.backends.sounddevice_backend import SoundDeviceBackend
            from ..pipeline import ConversationPipeline, PipelineConfig

            # Try to use real backends if available
            wake_detector = self._create_wake_detector()
            vad_backend = self._create_vad_backend()
            stt_engine = self._create_stt_engine()
            tts_engine = self._create_tts_engine()

            # Create audio backend with matching sample rate
            audio = SoundDeviceBackend(
                sample_rate=wake_detector.sample_rate,
                frame_length_ms=int(wake_detector.frame_length * 1000 / wake_detector.sample_rate),
            )

            # Create pipeline config
            config = PipelineConfig(
                vad_config=self.settings.vad.config,
            )

            # Create pipeline
            self._pipeline = ConversationPipeline(
                audio_backend=audio,
                wake_detector=wake_detector,
                vad_backend=vad_backend,
                stt_engine=stt_engine,
                tts_engine=tts_engine,
                response_handler=self._handle_transcription,
                config=config,
            )

            # Register event handler
            self._pipeline.on_event(self._on_pipeline_event)

            # Start pipeline
            self._pipeline.start()
            self._running = True

            # Start level monitoring
            self._level_timer.start(50)  # 20Hz

            self.state_changed.emit("idle")
            logger.info("Voice controller started")
            return True

        except ImportError as e:
            logger.warning(f"Voice dependencies not available: {e}")
            self.error_occurred.emit(f"Voice not available: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to start voice: {e}")
            self.error_occurred.emit(f"Failed to start: {e}")
            return False

    def stop(self):
        """Stop voice interaction."""
        if not self._running:
            return

        self._level_timer.stop()

        if self._pipeline:
            self._pipeline.stop()
            self._pipeline = None

        self._running = False
        self.state_changed.emit("stopped")
        logger.info("Voice controller stopped")

    def is_running(self) -> bool:
        """Check if voice is running."""
        return self._running

    def push_to_talk_start(self):
        """Start push-to-talk recording.

        Bypasses wake word and starts recording immediately.
        Call push_to_talk_stop() when user releases the button.
        """
        if not self._running or not self._pipeline:
            logger.warning("Cannot start push-to-talk: voice not running")
            return

        if self._push_to_talk_active:
            return  # Already active

        self._push_to_talk_active = True

        # Play feedback sound
        self._audio_feedback.play(FeedbackSound.RECORDING_START)

        # Trigger recording in pipeline (bypass wake word)
        if hasattr(self._pipeline, 'start_recording'):
            self._pipeline.start_recording()
        else:
            # Fallback: simulate wake word detection
            logger.info("Push-to-talk: starting recording")
            self._emit_state.emit("recording")

    def push_to_talk_stop(self):
        """Stop push-to-talk recording and process.

        Called when user releases the push-to-talk button.
        """
        if not self._push_to_talk_active:
            return

        self._push_to_talk_active = False

        # Play feedback sound
        self._audio_feedback.play(FeedbackSound.RECORDING_END)

        # Stop recording and process
        if self._pipeline and hasattr(self._pipeline, 'stop_recording'):
            self._pipeline.stop_recording()
        else:
            logger.info("Push-to-talk: stopping recording")

    def is_push_to_talk_active(self) -> bool:
        """Check if push-to-talk is currently active."""
        return self._push_to_talk_active

    def set_audio_feedback_enabled(self, enabled: bool):
        """Enable or disable audio feedback."""
        self._audio_feedback.set_enabled(enabled)
        self.settings.voice.audio_feedback_enabled = enabled

    def _create_wake_detector(self):
        """Create wake word detector based on settings."""
        try:
            from ..wake.backends.porcupine import PorcupineDetector
            return PorcupineDetector(
                keywords=self.settings.wake_word.keywords,
                sensitivity=self.settings.wake_word.sensitivity,
            )
        except Exception as e:
            logger.warning(f"Porcupine not available, using mock: {e}")
            from ..wake.backends.mock import MockWakeWordDetector
            return MockWakeWordDetector(
                keywords=self.settings.wake_word.keywords,
            )

    def _create_vad_backend(self):
        """Create VAD backend based on settings."""
        try:
            from ..vad.backends.silero import SileroVAD
            return SileroVAD()
        except Exception as e:
            logger.warning(f"Silero VAD not available, using mock: {e}")
            from ..vad.backends.mock import MockVAD
            return MockVAD()

    def _create_stt_engine(self):
        """Create STT engine based on settings."""
        try:
            from ..stt.backends.leopard import LeopardSTT
            return LeopardSTT()
        except Exception as e:
            logger.warning(f"Leopard STT not available, using mock: {e}")
            from ..stt.backends.mock import MockSTT
            return MockSTT()

    def _create_tts_engine(self):
        """Create TTS engine based on settings."""
        try:
            from ..tts.backends.orca import OrcaTTS
            return OrcaTTS()
        except Exception as e:
            logger.warning(f"Orca TTS not available, using mock: {e}")
            from ..tts.backends.mock import MockTTS
            return MockTTS()

    def _handle_transcription(self, text: str) -> str:
        """Handle transcription and get response."""
        if self._response_handler:
            return self._response_handler(text)
        return f"I heard: {text}"

    def _on_pipeline_event(self, event: PipelineEvent):
        """Handle pipeline events and emit Qt signals (thread-safe).

        This method may be called from background threads, so we use
        internal signals with QueuedConnection to safely emit to the main thread.
        Also plays audio feedback for key events.
        """
        if event.type == EventType.STATE_CHANGED:
            state = event.data.get("new_state", "")
            # Handle PipelineState enum
            if hasattr(state, 'name'):
                state = state.name.lower()
            # Map pipeline states to UI states
            state_map = {
                "idle": "idle",
                "listening": "listening",
                "wake_detected": "wake_detected",
                "recording": "recording",
                "processing": "processing",
                "speaking": "speaking",
            }
            ui_state = state_map.get(str(state).lower(), str(state))
            self._current_state = ui_state
            self._emit_state.emit(ui_state)

        elif event.type == EventType.WAKE_WORD_DETECTED:
            keyword = event.data.get("keyword", "")
            # Play wake word detected sound
            self._audio_feedback.play(FeedbackSound.WAKE_DETECTED)
            self._emit_wake.emit(keyword)
            self._emit_state.emit("wake_detected")

        elif event.type == EventType.RECORDING_STARTED:
            # Play recording start sound (if not from push-to-talk which already played)
            if not self._push_to_talk_active:
                self._audio_feedback.play(FeedbackSound.RECORDING_START)
            self._current_state = "recording"
            self._emit_state.emit("recording")

        elif event.type == EventType.RECORDING_STOPPED:
            # Play recording end sound (if not from push-to-talk which already played)
            if not self._push_to_talk_active:
                self._audio_feedback.play(FeedbackSound.RECORDING_END)
            self._current_state = "processing"
            self._emit_state.emit("processing")

        elif event.type == EventType.TRANSCRIPTION_COMPLETE:
            text = event.data.get("text", "")
            if text:
                self._emit_transcription.emit(text)

        elif event.type == EventType.RESPONSE_TEXT:
            text = event.data.get("text", "")
            self._emit_response.emit(text)

        elif event.type == EventType.TTS_STARTED:
            self._emit_tts_started.emit()
            self._current_state = "speaking"
            self._emit_state.emit("speaking")

        elif event.type == EventType.TTS_COMPLETE:
            # Play success sound when response complete
            self._audio_feedback.play(FeedbackSound.SUCCESS)
            self._emit_tts_finished.emit()
            self._current_state = "idle"
            self._emit_state.emit("idle")

        elif event.type == EventType.ERROR:
            error = event.data.get("error", "Unknown error")
            # Play error sound
            self._audio_feedback.play(FeedbackSound.ERROR)
            self._emit_error.emit(error)

    def _update_level(self):
        """Update audio level from pipeline."""
        # TODO: Get actual audio level from pipeline
        # For now, emit a simulated level based on state
        if self._running and self._pipeline:
            # This would be replaced with actual level from audio stream
            import random
            if self._current_state == "recording":
                level = 0.3 + random.random() * 0.5
            elif self._current_state == "speaking":
                level = 0.2 + random.random() * 0.4
            else:
                level = 0.05 + random.random() * 0.1
            self.level_changed.emit(level)

