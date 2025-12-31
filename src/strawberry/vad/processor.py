"""VAD processor with weighted counter algorithm."""

from dataclasses import dataclass
from typing import Optional
import numpy as np

from .base import VADBackend


@dataclass
class VADConfig:
    """Configuration for VAD processor.
    
    The algorithm uses a "speech buffer" that fills during speech
    and drains during silence. Recording ends when the buffer empties.
    
    Attributes:
        max_buffer: Maximum buffer level (hard cap)
        initial_buffer: Starting buffer level (grace period)
        base_decay: Rate of buffer drainage during silence
        growth_rate: Rate of buffer fill during speech (typically > base_decay)
        long_talk_threshold: Seconds before aggressive decay kicks in
        decay_multiplier_rate: How fast decay accelerates after threshold
    """
    max_buffer: float = 2.0
    initial_buffer: float = 1.5
    base_decay: float = 1.0
    growth_rate: float = 2.0
    long_talk_threshold: float = 8.0
    decay_multiplier_rate: float = 0.5


class VADProcessor:
    """Voice Activity Detection with weighted counter algorithm.
    
    This algorithm:
    - Builds momentum during speech (fills buffer)
    - Filters short noise bursts (they don't fill buffer enough)
    - Gets more aggressive at closing for long sessions
    
    Usage:
        processor = VADProcessor(vad_backend, config)
        processor.reset()  # Start new recording session
        
        for frame in audio_frames:
            if processor.process(frame):
                # Speech ended
                break
    """
    
    def __init__(
        self, 
        vad: VADBackend, 
        config: Optional[VADConfig] = None,
        frame_duration_ms: int = 30,
    ):
        """Initialize VAD processor.
        
        Args:
            vad: VAD backend for speech detection
            config: Algorithm configuration (uses defaults if None)
            frame_duration_ms: Duration of each audio frame in milliseconds
        """
        self.vad = vad
        self.config = config or VADConfig()
        self._frame_duration = frame_duration_ms / 1000.0  # Convert to seconds
        
        self._counter = 0.0
        self._session_duration = 0.0
        self._is_recording = False
        self._speech_detected = False  # Track if any speech was detected
    
    def reset(self) -> None:
        """Reset for a new recording session.
        
        Call this when starting to record user speech.
        """
        self._counter = self.config.initial_buffer
        self._session_duration = 0.0
        self._is_recording = True
        self._speech_detected = False
    
    def process(self, frame: np.ndarray) -> bool:
        """Process an audio frame.
        
        Args:
            frame: Audio samples (int16)
            
        Returns:
            True if speech has ended (stop recording), False to continue
        """
        if not self._is_recording:
            return True
        
        is_speaking = self.vad.is_speech(frame)
        self._session_duration += self._frame_duration
        
        if is_speaking:
            self._speech_detected = True
            # Refill buffer faster than it drains (reward speech)
            self._counter = min(
                self.config.max_buffer,
                self._counter + (self._frame_duration * self.config.growth_rate)
            )
        else:
            # Calculate decay multiplier (increases over time for long sessions)
            time_over_threshold = max(
                0.0,
                self._session_duration - self.config.long_talk_threshold
            )
            multiplier = 1.0 + (time_over_threshold * self.config.decay_multiplier_rate)
            
            # Drain the buffer
            self._counter -= (self._frame_duration * self.config.base_decay * multiplier)
        
        # Check if recording should end
        if self._counter <= 0:
            self._is_recording = False
            return True
        
        return False
    
    @property
    def counter(self) -> float:
        """Current buffer level.
        
        Useful for debugging or UI visualization.
        """
        return self._counter
    
    @property
    def session_duration(self) -> float:
        """How long the current recording has been running (seconds)."""
        return self._session_duration
    
    @property
    def is_recording(self) -> bool:
        """Whether the processor is in recording state."""
        return self._is_recording
    
    @property
    def speech_detected(self) -> bool:
        """Whether any speech was detected during this session."""
        return self._speech_detected
    
    def force_stop(self) -> None:
        """Force stop recording (e.g., on timeout)."""
        self._is_recording = False
        self._counter = 0.0

