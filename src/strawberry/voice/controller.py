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
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type

from ..config import Settings
from ..stt import STTEngine, discover_stt_modules
from ..tts import TTSEngine, discover_tts_modules
from ..vad import VADBackend, VADProcessor, discover_vad_modules
from ..wake import WakeWordDetector, discover_wake_modules
from .state import VoiceState, VoiceStateError, can_transition

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
        
        # Audio stream (kept open to avoid frame loss)
        self._audio_stream = None
        self._audio_buffer: List[bytes] = []
        
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
        
        # Fallback to mock if not found
        if not stt_cls:
            stt_cls = stt_modules.get("mock")
            logger.warning(f"STT backend '{self._config.stt_backend}' not found, using mock")
        
        if not tts_cls:
            tts_cls = tts_modules.get("mock")
            logger.warning(f"TTS backend '{self._config.tts_backend}' not found, using mock")
        
        if not vad_cls:
            vad_cls = vad_modules.get("mock")
            logger.warning(f"VAD backend '{self._config.vad_backend}' not found, using mock")
        
        if not wake_cls:
            wake_cls = wake_modules.get("mock")
            logger.warning(f"Wake backend '{self._config.wake_backend}' not found, using mock")
        
        # Instantiate backends with graceful fallback on init errors
        # (e.g., missing API keys)
        if wake_cls:
            try:
                self._wake_detector = wake_cls(
                    keywords=self._config.wake_words,
                    sensitivity=self._config.sensitivity,
                )
            except Exception as e:
                logger.warning(f"Wake backend '{wake_cls.__name__}' init failed: {e}, using mock")
                mock_wake_cls = wake_modules.get("mock")
                if mock_wake_cls:
                    self._wake_detector = mock_wake_cls(
                        keywords=self._config.wake_words,
                        sensitivity=self._config.sensitivity,
                    )
        
        if vad_cls:
            try:
                self._vad = vad_cls(sample_rate=self._config.sample_rate)
            except Exception as e:
                logger.warning(f"VAD backend '{vad_cls.__name__}' init failed: {e}, using mock")
                mock_vad_cls = vad_modules.get("mock")
                if mock_vad_cls:
                    self._vad = mock_vad_cls(sample_rate=self._config.sample_rate)
        
        # STT and TTS classes are stored for lazy initialization
        # They'll be initialized when needed with proper error handling
        self._stt_cls = stt_cls
        self._tts_cls = tts_cls
    
    async def _cleanup_components(self) -> None:
        """Cleanup voice pipeline components."""
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
    
    async def push_to_talk_start(self) -> None:
        """Start push-to-talk recording."""
        if self._state != VoiceState.IDLE:
            logger.warning(f"Cannot start PTT in state {self._state.name}")
            return
        
        self._ptt_active = True
        self._audio_buffer.clear()
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
