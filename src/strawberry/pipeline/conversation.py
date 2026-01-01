"""Conversation pipeline orchestrator."""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Callable, List
import threading
import time
import numpy as np

from ..audio.base import AudioBackend
from ..audio.stream import AudioStream
from ..audio.playback import AudioPlayer
from ..wake.base import WakeWordDetector
from ..vad.base import VADBackend
from ..vad.processor import VADProcessor, VADConfig
from ..stt.base import STTEngine, TranscriptionResult
from ..tts.base import TTSEngine

from .events import PipelineEvent, EventType


class PipelineState(Enum):
    """States of the conversation pipeline."""
    
    IDLE = auto()        # Not started
    LISTENING = auto()   # Waiting for wake word
    RECORDING = auto()   # Capturing user speech
    PROCESSING = auto()  # Transcribing / waiting for response
    SPEAKING = auto()    # Playing TTS response
    PAUSED = auto()      # Temporarily paused


@dataclass
class PipelineConfig:
    """Configuration for the conversation pipeline.
    
    Attributes:
        max_recording_duration: Maximum seconds to record
        lookback_frames: Frames to include from before wake word
        interrupt_enabled: Allow user to interrupt TTS playback
        processing_timeout: Maximum seconds for STT + LLM processing
        vad_config: VAD algorithm configuration
    """
    max_recording_duration: float = 30.0
    lookback_frames: int = 10
    interrupt_enabled: bool = True
    processing_timeout: float = 60.0  # 60 second timeout for processing
    vad_config: VADConfig = field(default_factory=VADConfig)


class ConversationPipeline:
    """Orchestrates the full voice conversation flow.
    
    State machine:
        IDLE → LISTENING (on start)
        LISTENING → RECORDING (on wake word)
        RECORDING → PROCESSING (on VAD speech end or timeout)
        PROCESSING → SPEAKING (on response)
        SPEAKING → LISTENING (on TTS complete)
        SPEAKING → RECORDING (on interrupt, if enabled)
        Any → PAUSED (on pause)
        PAUSED → previous (on resume)
    """
    
    def __init__(
        self,
        audio_backend: AudioBackend,
        wake_detector: WakeWordDetector,
        vad_backend: VADBackend,
        stt_engine: STTEngine,
        tts_engine: TTSEngine,
        response_handler: Optional[Callable[[str], str]] = None,
        config: Optional[PipelineConfig] = None,
    ):
        """Initialize the conversation pipeline.
        
        Args:
            audio_backend: Audio input backend
            wake_detector: Wake word detector
            vad_backend: Voice activity detector
            stt_engine: Speech-to-text engine
            tts_engine: Text-to-speech engine
            response_handler: Function(user_text) -> response_text
                            If None, echoes user input
            config: Pipeline configuration
        """
        self.config = config or PipelineConfig()
        
        # Components
        self._audio_stream = AudioStream(audio_backend)
        self._wake_detector = wake_detector
        self._vad_processor = VADProcessor(
            vad_backend,
            self.config.vad_config,
            frame_duration_ms=audio_backend.frame_length_ms,
        )
        self._stt_engine = stt_engine
        self._tts_engine = tts_engine
        self._response_handler = response_handler or (lambda x: f"You said: {x}")
        
        # Audio player for TTS output
        self._audio_player = AudioPlayer(
            sample_rate=tts_engine.sample_rate if tts_engine else 22050
        )
        
        # State
        self._state = PipelineState.IDLE
        self._previous_state = PipelineState.IDLE
        self._recording_buffer: List[np.ndarray] = []
        self._recording_start_time: float = 0
        
        # Event handling
        self._event_handlers: List[Callable[[PipelineEvent], None]] = []
        self._lock = threading.Lock()
    
    @property
    def state(self) -> PipelineState:
        """Current pipeline state."""
        return self._state
    
    def on_event(self, handler: Callable[[PipelineEvent], None]) -> None:
        """Register an event handler.
        
        Args:
            handler: Function to call with each pipeline event
        """
        self._event_handlers.append(handler)
    
    def _emit(self, event_type: EventType, data=None) -> None:
        """Emit a pipeline event."""
        event = PipelineEvent(type=event_type, data=data)
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception:
                pass  # Don't let handler errors crash pipeline
    
    def _set_state(self, new_state: PipelineState) -> None:
        """Change pipeline state and emit event."""
        old_state = self._state
        self._state = new_state
        self._emit(EventType.STATE_CHANGED, {
            "old_state": old_state,
            "new_state": new_state,
        })
    
    def start(self) -> None:
        """Start the conversation pipeline."""
        if self._state != PipelineState.IDLE:
            return
        
        # Subscribe to audio stream
        self._audio_stream.subscribe(self._on_audio_frame)
        self._audio_stream.start()
        
        self._set_state(PipelineState.LISTENING)
    
    def stop(self) -> None:
        """Stop the conversation pipeline."""
        self._audio_stream.unsubscribe(self._on_audio_frame)
        self._audio_stream.stop()
        self._set_state(PipelineState.IDLE)
    
    def pause(self) -> None:
        """Pause the pipeline."""
        if self._state not in (PipelineState.IDLE, PipelineState.PAUSED):
            self._previous_state = self._state
            self._set_state(PipelineState.PAUSED)
    
    def resume(self) -> None:
        """Resume from paused state."""
        if self._state == PipelineState.PAUSED:
            self._set_state(self._previous_state)
    
    def start_recording(self) -> bool:
        """Start recording immediately (for push-to-talk).
        
        Bypasses wake word detection and starts recording directly.
        
        Returns:
            True if recording started, False otherwise
        """
        if self._state not in (PipelineState.LISTENING, PipelineState.IDLE):
            return False
        
        self._start_recording()
        return True
    
    def stop_recording(self) -> bool:
        """Stop recording and process (for push-to-talk).
        
        Returns:
            True if recording was stopped, False otherwise
        """
        if self._state != PipelineState.RECORDING:
            return False
        
        self._finish_recording()
        return True
    
    def _on_audio_frame(self, frame: np.ndarray) -> None:
        """Handle incoming audio frame based on current state."""
        if self._state == PipelineState.LISTENING:
            self._handle_listening(frame)
        elif self._state == PipelineState.RECORDING:
            self._handle_recording(frame)
        elif self._state == PipelineState.SPEAKING:
            if self.config.interrupt_enabled:
                self._check_interrupt(frame)
    
    def _handle_listening(self, frame: np.ndarray) -> None:
        """Process frame while waiting for wake word."""
        keyword_index = self._wake_detector.process(frame)
        
        if keyword_index >= 0:
            keyword = self._wake_detector.keywords[keyword_index]
            self._emit(EventType.WAKE_WORD_DETECTED, {"keyword": keyword})
            self._start_recording()
    
    def _start_recording(self) -> None:
        """Transition to recording state."""
        self._set_state(PipelineState.RECORDING)
        self._emit(EventType.RECORDING_STARTED)
        
        # Include lookback buffer (audio from before wake word)
        lookback = self._audio_stream.get_buffer(self.config.lookback_frames)
        self._recording_buffer = [lookback] if len(lookback) > 0 else []
        
        # Reset VAD processor
        self._vad_processor.reset()
        self._recording_start_time = time.time()
    
    def _handle_recording(self, frame: np.ndarray) -> None:
        """Process frame while recording user speech."""
        self._recording_buffer.append(frame)
        
        # Check for timeout
        elapsed = time.time() - self._recording_start_time
        if elapsed > self.config.max_recording_duration:
            self._finish_recording()
            return
        
        # Update VAD
        speech_ended = self._vad_processor.process(frame)
        
        if speech_ended:
            self._emit(EventType.VAD_SPEECH_END)
            self._finish_recording()
    
    def _finish_recording(self) -> None:
        """Transition from recording to processing."""
        self._emit(EventType.RECORDING_STOPPED)
        self._set_state(PipelineState.PROCESSING)
        
        # Concatenate all recorded audio
        if self._recording_buffer:
            audio = np.concatenate(self._recording_buffer)
        else:
            audio = np.array([], dtype=np.int16)
        self._recording_buffer = []
        
        # Process in separate thread with timeout to not block audio
        def processing_with_timeout():
            self._process_speech(audio)
        
        processing_thread = threading.Thread(
            target=processing_with_timeout,
            daemon=True,
        )
        processing_thread.start()
        
        # Monitor timeout in separate thread
        def monitor_timeout():
            processing_thread.join(timeout=self._config.processing_timeout)
            if processing_thread.is_alive():
                # Processing timed out
                self._emit(EventType.ERROR, {
                    "error": f"Processing timeout after {self._config.processing_timeout}s",
                    "stage": "processing"
                })
                # Force state back to listening
                self._set_state(PipelineState.LISTENING)
        
        threading.Thread(target=monitor_timeout, daemon=True).start()
    
    def _process_speech(self, audio: np.ndarray) -> None:
        """Transcribe audio and generate response."""
        self._emit(EventType.TRANSCRIPTION_STARTED)
        
        # Transcribe
        try:
            result = self._stt_engine.transcribe(audio)
        except Exception as e:
            self._emit(EventType.ERROR, {"error": str(e), "stage": "stt"})
            self._set_state(PipelineState.LISTENING)
            return
        
        self._emit(EventType.TRANSCRIPTION_COMPLETE, {
            "text": result.text,
            "confidence": result.confidence,
        })
        
        if not result.text.strip():
            # No speech detected
            self._set_state(PipelineState.LISTENING)
            return
        
        # Get response
        self._emit(EventType.RESPONSE_STARTED)
        try:
            response_text = self._response_handler(result.text)
        except Exception as e:
            self._emit(EventType.ERROR, {"error": str(e), "stage": "response"})
            self._set_state(PipelineState.LISTENING)
            return
        
        self._emit(EventType.RESPONSE_TEXT, {"text": response_text})
        self._emit(EventType.RESPONSE_COMPLETE)
        
        # Speak response
        self._speak_response(response_text)
    
    def _speak_response(self, text: str) -> None:
        """Synthesize and play response."""
        self._set_state(PipelineState.SPEAKING)
        self._emit(EventType.TTS_STARTED, {"text": text})
        
        try:
            for chunk in self._tts_engine.synthesize_stream(text):
                if self._state != PipelineState.SPEAKING:
                    # Interrupted
                    self._audio_player.stop()
                    break
                self._emit(EventType.TTS_CHUNK, {
                    "samples": len(chunk.audio),
                    "duration": chunk.duration_sec,
                })
                # Play the audio chunk
                self._audio_player.play(
                    chunk.audio, 
                    sample_rate=chunk.sample_rate,
                    blocking=True  # Wait for chunk to finish
                )
        except Exception as e:
            self._emit(EventType.ERROR, {"error": str(e), "stage": "tts"})
        
        self._emit(EventType.TTS_COMPLETE)
        
        if self._state == PipelineState.SPEAKING:
            self._set_state(PipelineState.LISTENING)
    
    def _check_interrupt(self, frame: np.ndarray) -> None:
        """Check if user is interrupting TTS playback."""
        # For interrupts, we could check for loud audio or wake word
        # For now, we'll check for wake word
        keyword_index = self._wake_detector.process(frame)
        if keyword_index >= 0:
            self._emit(EventType.WAKE_WORD_DETECTED, {
                "keyword": self._wake_detector.keywords[keyword_index],
                "interrupt": True,
            })
            self._start_recording()
    
    # --- Synchronous API for testing ---
    
    def process_text(self, text: str) -> str:
        """Process text input directly (bypasses audio/STT).
        
        Useful for testing and text-only mode.
        
        Args:
            text: User input text
            
        Returns:
            Response text
        """
        return self._response_handler(text)

