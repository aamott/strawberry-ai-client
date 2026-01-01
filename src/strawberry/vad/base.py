"""Abstract base class for Voice Activity Detection backends."""

from abc import ABC, abstractmethod

import numpy as np


class VADBackend(ABC):
    """Abstract base class for Voice Activity Detection.
    
    All VAD backends must implement this interface to be pluggable.
    """

    @abstractmethod
    def __init__(self, sample_rate: int = 16000):
        """Initialize the VAD backend.
        
        Args:
            sample_rate: Expected audio sample rate in Hz
        """
        pass

    @abstractmethod
    def is_speech(self, audio_frame: np.ndarray) -> bool:
        """Determine if audio frame contains speech.
        
        Args:
            audio_frame: Audio samples (int16)
            
        Returns:
            True if speech detected, False otherwise
        """
        pass

    @abstractmethod
    def get_probability(self, audio_frame: np.ndarray) -> float:
        """Get speech probability for audio frame.
        
        Args:
            audio_frame: Audio samples (int16)
            
        Returns:
            Probability of speech (0.0 to 1.0)
        """
        pass

    def cleanup(self) -> None:
        """Release any resources held by the backend.
        
        Override in subclasses that need cleanup.
        """
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False

