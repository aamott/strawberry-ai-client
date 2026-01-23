"""Pure-Python voice controller (Qt-independent).

This module provides the voice pipeline controller that manages:
- Wake word detection
- Voice activity detection (VAD)
- Speech-to-text (STT)
- Text-to-speech (TTS)
- State machine for voice interaction

The audio stream remains open throughout the voice session to prevent
frame loss between components.
"""

import asyncio
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

import numpy as np

from .audio.backends.sounddevice_backend import SoundDeviceBackend
from .audio.playback import AudioPlayer
from .audio.stream import AudioStream
from .state import VoiceState, VoiceStateError, can_transition
from .stt import STTEngine, discover_stt_modules
from .tts import TTSEngine, discover_tts_modules
from .vad import VADBackend, VADProcessor, discover_vad_modules
from .wakeword import WakeWordDetector, discover_wake_modules

logger = logging.getLogger(__name__)


@dataclass
class VoiceEvent:
    """Base class for voice events."""
    session_id: str = ""


@dataclass
class VoiceStatusChanged(VoiceEvent):
    """Voice state has changed."""
    state: VoiceState = VoiceState.STOPPED
    previous_state: VoiceState = VoiceState.STOPPED


@dataclass
class VoiceWakeWordDetected(VoiceEvent):
    """Wake word was detected."""
    keyword: str = ""
    keyword_index: int = 0


@dataclass
class VoiceListening(VoiceEvent):
    """Voice is now listening for speech."""
    pass


@dataclass
class VoiceTranscription(VoiceEvent):
    """Speech was transcribed."""
    text: str = ""
    is_final: bool = True


@dataclass
class VoiceResponse(VoiceEvent):
    """Response text (for TTS or display)."""
    text: str = ""


@dataclass
class VoiceSpeaking(VoiceEvent):
    """TTS is playing response."""
    text: str = ""


@dataclass
class VoiceError(VoiceEvent):
    """An error occurred in voice pipeline."""
    error: str = ""
    exception: Optional[Exception] = None


@dataclass
class VoiceConfig:
    """Configuration for voice controller."""
    wake_words: List[str] = field(default_factory=lambda: ["strawberry"])
    sensitivity: float = 0.5
    sample_rate: int = 16000
    audio_feedback_enabled: bool = True

    # Backend selection (module names)
    stt_backend: str = "leopard"
    tts_backend: str = "orca"
    vad_backend: str = "silero"
    wake_backend: str = "porcupine"


class VoiceController:
    """Pure-Python voice controller.

    Manages the voice interaction pipeline including wake word detection,
    speech recognition, and text-to-speech. Uses asyncio for event handling.

    The audio stream is kept open throughout the voice session to prevent
    frame loss between wake word detection and STT.

    Usage:
        controller = VoiceController(config)
        controller.add_listener(my_event_handler)
        await controller.start()
        # ... voice interaction happens ...
        await controller.stop()
    """

    def __init__(
        self,
        config: VoiceConfig,
        response_handler: Optional[Callable[[str], str]] = None,
    ):
        """Initialize voice controller.

        Args:
            config: Voice configuration
            response_handler: Async callback(transcription) -> response_text
        """
        self._config = config
        self._response_handler = response_handler

        # State
        self._state = VoiceState.STOPPED
        self._state_lock = threading.Lock()
        self._session_id = ""
        self._session_counter = 0

        # Components (lazy initialized)
        self._wake_detector: Optional[WakeWordDetector] = None
        self._vad: Optional[VADBackend] = None
        self._vad_processor: Optional[VADProcessor] = None
        self._stt: Optional[STTEngine] = None
        self._tts: Optional[TTSEngine] = None
        self._audio_player: Optional[AudioPlayer] = None

        # Audio stream (kept open to avoid frame loss)
        self._audio_backend: Optional[SoundDeviceBackend] = None
        self._audio_stream: Optional[AudioStream] = None
        self._recording_buffer: List[np.ndarray] = []
        self._recording_start_time: float = 0
        self._max_recording_duration: float = 30.0  # Max seconds to record

        # Event listeners
        self._listeners: List[Callable[[VoiceEvent], Any]] = []

        # Push-to-talk state
        self._ptt_active = False

    @property
    def state(self) -> VoiceState:
        """Current voice state."""
        return self._state

    @property
    def session_id(self) -> str:
        """Current voice session ID."""
        return self._session_id

    def add_listener(self, listener: Callable[[VoiceEvent], Any]) -> None:
        """Add event listener.

        Args:
            listener: Callback function(event) for voice events
        """
        self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[VoiceEvent], Any]) -> None:
        """Remove event listener."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _emit(self, event: VoiceEvent) -> None:
        """Emit event to all listeners."""
        event.session_id = self._session_id
        for listener in self._listeners:
            try:
                result = listener(event)
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)
            except Exception as e:
                logger.error(f"Error in voice event listener: {e}")

    def _transition_to(self, new_state: VoiceState) -> None:
        """Transition to a new state.

        Args:
            new_state: Target state

        Raises:
            VoiceStateError: If transition is not valid
        """
        with self._state_lock:
            if not can_transition(self._state, new_state):
                raise VoiceStateError(self._state, new_state)

            old_state = self._state
            self._state = new_state
            logger.debug(f"Voice state: {old_state.name} → {new_state.name}")

        self._emit(VoiceStatusChanged(
            state=new_state,
            previous_state=old_state,
        ))

    async def start(self) -> bool:
        """Start voice controller.

        Returns:
            True if started successfully
        """
        if self._state != VoiceState.STOPPED:
            logger.warning("Voice controller already running")
            return False

        try:
            # Initialize components
            await self._init_components()

            # Generate new session ID
            self._session_counter += 1
            self._session_id = f"voice-{self._session_counter}"

            # Start audio stream and subscribe to frames
            if self._audio_stream:
                self._audio_stream.subscribe(self._on_audio_frame)
                self._audio_stream.start()
                logger.info(f"Listening for wake words: {self._config.wake_words}")

            # Transition to IDLE
            self._transition_to(VoiceState.IDLE)

            logger.info("Voice controller started")
            return True

        except Exception as e:
            logger.error(f"Failed to start voice controller: {e}")
            self._emit(VoiceError(error=str(e), exception=e))
            return False

    async def stop(self) -> None:
        """Stop voice controller."""
        if self._state == VoiceState.STOPPED:
            return

        try:
            self._transition_to(VoiceState.STOPPED)
        except VoiceStateError:
            # Force stop from any state
            with self._state_lock:
                self._state = VoiceState.STOPPED

        # Cleanup components
        await self._cleanup_components()

        logger.info("Voice controller stopped")

    async def _init_components(self) -> None:
        """Initialize voice pipeline components."""
        # Discover and instantiate backends
        stt_modules = discover_stt_modules()
        tts_modules = discover_tts_modules()
        vad_modules = discover_vad_modules()
        wake_modules = discover_wake_modules()

        # Get backend classes
        stt_cls = stt_modules.get(self._config.stt_backend)
        tts_cls = tts_modules.get(self._config.tts_backend)
        vad_cls = vad_modules.get(self._config.vad_backend)
        wake_cls = wake_modules.get(self._config.wake_backend)

        if not stt_cls:
            raise RuntimeError(
                f"STT backend '{self._config.stt_backend}' not found. "
                "Check settings and available STT modules."
            )

        if not tts_cls:
            raise RuntimeError(
                f"TTS backend '{self._config.tts_backend}' not found. "
                "Check settings and available TTS modules."
            )

        if not vad_cls:
            raise RuntimeError(
                f"VAD backend '{self._config.vad_backend}' not found. "
                "Check settings and available VAD modules."
            )

        if not wake_cls:
            raise RuntimeError(
                f"Wake backend '{self._config.wake_backend}' not found. "
                "Check settings and available wake modules."
            )

        # Instantiate wake word detector first to get required frame length
        if wake_cls:
            try:
                self._wake_detector = wake_cls(
                    keywords=self._config.wake_words,
                    sensitivity=self._config.sensitivity,
                )
            except Exception as e:
                logger.error(f"Wake backend '{wake_cls.__name__}' init failed: {e}")
                raise RuntimeError(
                    "Wake word initialization failed. Check wake word settings, "
                    "backend dependencies, and API keys."
                ) from e

        # Initialize audio backend matching wake word detector's requirements
        if self._wake_detector:
            # Calculate frame_length_ms from wake detector's requirements
            wake_frame_len = self._wake_detector.frame_length
            wake_sample_rate = self._wake_detector.sample_rate
            frame_ms = int(wake_frame_len * 1000 / wake_sample_rate)
            self._audio_backend = SoundDeviceBackend(
                sample_rate=wake_sample_rate,
                frame_length_ms=frame_ms,
            )
            self._audio_stream = AudioStream(self._audio_backend)
            logger.info(
                f"Audio stream initialized: {wake_sample_rate}Hz, {frame_ms}ms frames"
            )

        if vad_cls:
            try:
                self._vad = vad_cls(sample_rate=self._config.sample_rate)
                # Create VAD processor with default config
                from .vad.processor import VADConfig
                frame_ms = int(
                    self._wake_detector.frame_length * 1000
                    / self._wake_detector.sample_rate
                ) if self._wake_detector else 32
                self._vad_processor = VADProcessor(
                    self._vad,
                    VADConfig(),
                    frame_duration_ms=frame_ms,
                )
            except Exception as e:
                logger.error(f"VAD init failed: {e}")
                raise RuntimeError(
                    "VAD initialization failed. Check VAD settings and dependencies."
                ) from e

        # Initialize STT engine
        if stt_cls:
            try:
                self._stt = stt_cls()
                logger.info(f"STT initialized: {stt_cls.__name__}")
            except Exception as e:
                logger.error(f"STT init failed: {e}")
                raise RuntimeError(
                    "STT initialization failed. Check STT settings and dependencies."
                ) from e

        # Initialize TTS engine
        if tts_cls:
            try:
                self._tts = tts_cls()
                self._audio_player = AudioPlayer(
                    sample_rate=self._tts.sample_rate if self._tts else 22050
                )
                logger.info(f"TTS initialized: {tts_cls.__name__}")
            except Exception as e:
                logger.error(f"TTS init failed: {e}")
                raise RuntimeError(
                    "TTS initialization failed. Check TTS settings and dependencies."
                ) from e

    async def _cleanup_components(self) -> None:
        """Cleanup voice pipeline components."""
        # Stop audio stream first
        if self._audio_stream:
            self._audio_stream.unsubscribe(self._on_audio_frame)
            self._audio_stream.stop()
            self._audio_stream = None

        if self._audio_backend:
            self._audio_backend = None

        if self._wake_detector:
            self._wake_detector.cleanup()
            self._wake_detector = None

        if self._vad:
            self._vad.cleanup()
            self._vad = None

        if self._stt:
            self._stt.cleanup()
            self._stt = None

        if self._tts:
            self._tts.cleanup()
            self._tts = None

    def set_response_handler(self, handler: Callable[[str], str]) -> None:
        """Set callback for processing transcriptions."""
        self._response_handler = handler

    def _on_audio_frame(self, frame) -> None:
        """Handle incoming audio frame based on current state.

        This is called by the AudioStream for each audio frame.
        - IDLE: Check for wake word detection
        - LISTENING: Record audio and check VAD for speech end

        Args:
            frame: Audio samples as numpy array (int16)
        """
        if self._state == VoiceState.IDLE:
            self._handle_idle(frame)
        elif self._state == VoiceState.LISTENING:
            self._handle_listening(frame)

    def _handle_idle(self, frame) -> None:
        """Process frame while in IDLE state - check for wake word."""
        if not self._wake_detector:
            return

        try:
            keyword_index = self._wake_detector.process(frame)

            if keyword_index >= 0:
                keyword = self._wake_detector.keywords[keyword_index]
                logger.info(f"Wake word detected: {keyword}")

                # Emit wake word event
                self._emit(VoiceWakeWordDetected(
                    keyword=keyword,
                    keyword_index=keyword_index,
                ))

                # Start recording
                self._start_recording()

        except Exception as e:
            logger.error(f"Error processing audio frame: {e}")

    def _start_recording(self) -> None:
        """Transition to listening and start recording audio."""
        self._recording_buffer.clear()
        self._recording_start_time = time.time()
        if self._vad_processor:
            self._vad_processor.reset()
        self._transition_to(VoiceState.LISTENING)
        self._emit(VoiceListening())
        logger.info("Started recording")

    def _handle_listening(self, frame) -> None:
        """Process frame while recording - buffer audio and check VAD."""
        # Add frame to recording buffer
        self._recording_buffer.append(frame)

        # Check for timeout
        elapsed = time.time() - self._recording_start_time
        if elapsed > self._max_recording_duration:
            logger.warning(f"Recording timed out after {elapsed:.1f}s")
            self._finish_recording()
            return

        # Check VAD for speech end
        if self._vad_processor:
            speech_ended = self._vad_processor.process(frame)
            if speech_ended:
                logger.info(
                    f"VAD speech end after {self._vad_processor.session_duration:.2f}s"
                )
                self._finish_recording()
        elif elapsed > 3.0:
            # No VAD - use simple timeout
            logger.info("Recording timeout (no VAD)")
            self._finish_recording()

    def _finish_recording(self) -> None:
        """Process recorded audio through STT and response handler."""
        self._transition_to(VoiceState.PROCESSING)

        # Concatenate all recorded audio
        if self._recording_buffer:
            audio = np.concatenate(self._recording_buffer)
        else:
            audio = np.array([], dtype=np.int16)
        self._recording_buffer.clear()

        logger.info(f"Recording finished: {len(audio)} samples")

        # Process in background thread to not block audio
        threading.Thread(
            target=self._process_audio_sync,
            args=(audio,),
            daemon=True,
        ).start()

    def _process_audio_sync(self, audio: np.ndarray) -> None:
        """Process audio through STT and get response (sync, runs in thread)."""
        try:
            # Transcribe
            if not self._stt:
                logger.warning("No STT engine available")
                self._transition_to(VoiceState.IDLE)
                return

            result = self._stt.transcribe(audio)
            text = result.text.strip() if result.text else ""

            if not text:
                logger.info("Empty transcription, returning to idle")
                self._transition_to(VoiceState.IDLE)
                return

            logger.info(f"Transcription: {text}")
            self._emit(VoiceTranscription(text=text, is_final=True))

            # Get response if handler set
            if self._response_handler:
                response = self._response_handler(text)
                logger.info(f"Response: {response[:50]}...")
                self._emit(VoiceResponse(text=response))

                # Speak the response
                self._speak_response(response)
            else:
                # No handler, return to idle
                self._transition_to(VoiceState.IDLE)

        except Exception as e:
            logger.error(f"Error processing audio: {e}")
            self._emit(VoiceError(error=str(e), exception=e))
            self._transition_to(VoiceState.IDLE)

    def _speak_response(self, text: str) -> None:
        """Speak response text using TTS.

        Strips code blocks and tool calls before speaking.
        """
        if not self._tts or not self._audio_player:
            logger.warning("No TTS engine available")
            self._transition_to(VoiceState.IDLE)
            return

        # Strip code blocks (```...```)
        speakable_text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        # Strip inline code (`...`)
        speakable_text = re.sub(r"`[^`]+`", "", speakable_text)
        # Clean up whitespace
        speakable_text = re.sub(r"\s+", " ", speakable_text).strip()

        if not speakable_text:
            logger.info("No speakable text after filtering")
            self._transition_to(VoiceState.IDLE)
            return

        try:
            self._transition_to(VoiceState.SPEAKING)
            self._emit(VoiceSpeaking(text=speakable_text))

            # Synthesize and play audio (streaming)
            for chunk in self._tts.synthesize_stream(speakable_text):
                if self._state != VoiceState.SPEAKING:
                    # Interrupted
                    self._audio_player.stop()
                    break
                self._audio_player.play(
                    chunk.audio,
                    sample_rate=chunk.sample_rate,
                    blocking=True,
                )

            logger.info("TTS playback complete")

        except Exception as e:
            logger.error(f"TTS playback failed: {e}")
            self._emit(VoiceError(error=str(e), exception=e))

        finally:
            # Return to idle
            if self._state == VoiceState.SPEAKING:
                self._transition_to(VoiceState.IDLE)

    async def push_to_talk_start(self) -> None:
        """Start push-to-talk recording."""
        if self._state != VoiceState.IDLE:
            logger.warning(f"Cannot start PTT in state {self._state.name}")
            return

        self._ptt_active = True
        self._recording_buffer.clear()
        self._transition_to(VoiceState.LISTENING)
        self._emit(VoiceListening())

    async def push_to_talk_stop(self) -> None:
        """Stop push-to-talk and process recording."""
        if not self._ptt_active or self._state != VoiceState.LISTENING:
            return

        self._ptt_active = False
        await self._process_recording()

    async def _process_recording(self) -> None:
        """Process recorded audio through STT and response handler."""
        try:
            self._transition_to(VoiceState.PROCESSING)

            # Transcription would happen here
            # For now just emit placeholder
            transcription = "Placeholder transcription"
            self._emit(VoiceTranscription(text=transcription, is_final=True))

            # Get response if handler set
            if self._response_handler:
                response = self._response_handler(transcription)
                self._emit(VoiceResponse(text=response))

                # TTS would happen here
                if self._tts:
                    self._transition_to(VoiceState.SPEAKING)
                    self._emit(VoiceSpeaking(text=response))
                    # ... play audio ...
                    self._transition_to(VoiceState.IDLE)
                else:
                    self._transition_to(VoiceState.IDLE)
            else:
                self._transition_to(VoiceState.IDLE)

        except Exception as e:
            logger.error(f"Error processing recording: {e}")
            self._emit(VoiceError(error=str(e), exception=e))
            self._transition_to(VoiceState.ERROR)
            self._transition_to(VoiceState.STOPPED)
