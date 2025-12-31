"""Abstract base class for wake word detection."""

from abc import ABC, abstractmethod
from typing import List
import numpy as np


class WakeWordDetector(ABC):
    """Abstract base class for wake word detection.
    
    All wake word backends must implement this interface.
    """
    
    @abstractmethod
    def __init__(self, keywords: List[str], sensitivity: float = 0.5):
        """Initialize the wake word detector.
        
        Args:
            keywords: List of wake words to detect
            sensitivity: Detection sensitivity (0.0 to 1.0)
                        Higher = more sensitive, more false positives
                        Lower = less sensitive, fewer false positives
        """
        pass
    
    @property
    @abstractmethod
    def keywords(self) -> List[str]:
        """List of wake words being detected."""
        pass
    
    @property
    @abstractmethod
    def frame_length(self) -> int:
        """Required audio frame length in samples."""
        pass
    
    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Required audio sample rate in Hz."""
        pass
    
    @abstractmethod
    def process(self, audio_frame: np.ndarray) -> int:
        """Process an audio frame for wake word detection.
        
        Args:
            audio_frame: Audio samples (int16), must be frame_length samples
            
        Returns:
            Index of detected keyword (0-based), or -1 if none detected
        """
        pass
    
    def cleanup(self) -> None:
        """Release any resources held by the detector.
        
        Override in subclasses that need cleanup.
        """
        pass
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False

