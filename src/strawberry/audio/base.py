"""Abstract base class for audio backends."""

from abc import ABC, abstractmethod
from typing import Iterator

import numpy as np


class AudioBackend(ABC):
    """Abstract base class for audio input backends.
    
    All audio backends must implement this interface to be pluggable.
    """

    def __init__(self, sample_rate: int = 16000, frame_length_ms: int = 30):
        """Initialize the audio backend.
        
        Args:
            sample_rate: Audio sample rate in Hz (default 16000 for most STT)
            frame_length_ms: Length of each audio frame in milliseconds
        """
        self._sample_rate = sample_rate
        self._frame_length_ms = frame_length_ms

    @property
    def sample_rate(self) -> int:
        """Audio sample rate in Hz."""
        return self._sample_rate

    @property
    def frame_length_ms(self) -> int:
        """Frame length in milliseconds."""
        return self._frame_length_ms

    @property
    def frame_length(self) -> int:
        """Number of samples per frame."""
        return int(self._sample_rate * self._frame_length_ms / 1000)

    @abstractmethod
    def start(self) -> None:
        """Start the audio stream."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop the audio stream."""
        pass

    @abstractmethod
    def read_frame(self) -> np.ndarray:
        """Read a single audio frame.
        
        Returns:
            numpy array of audio samples (int16)
            
        Raises:
            RuntimeError: If stream is not active
        """
        pass

    def frames(self) -> Iterator[np.ndarray]:
        """Yield audio frames continuously.
        
        Yields:
            numpy arrays of audio samples (int16)
        """
        while self.is_active:
            yield self.read_frame()

    @property
    @abstractmethod
    def is_active(self) -> bool:
        """Check if stream is currently active."""
        pass

    def __enter__(self):
        """Context manager entry - start stream."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - stop stream."""
        self.stop()
        return False

