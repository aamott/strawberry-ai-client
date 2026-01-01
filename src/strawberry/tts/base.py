"""Abstract base class for Text-to-Speech engines."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator

import numpy as np


@dataclass
class AudioChunk:
    """Chunk of synthesized audio.
    
    Attributes:
        audio: Audio samples (int16)
        sample_rate: Sample rate in Hz
    """
    audio: np.ndarray
    sample_rate: int

    @property
    def duration_sec(self) -> float:
        """Duration of this chunk in seconds."""
        return len(self.audio) / self.sample_rate


class TTSEngine(ABC):
    """Abstract base class for Text-to-Speech engines.
    
    All TTS backends must implement this interface.
    """

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Output audio sample rate in Hz."""
        pass

    @abstractmethod
    def synthesize(self, text: str) -> AudioChunk:
        """Synthesize complete text to audio.
        
        Args:
            text: Text to synthesize
            
        Returns:
            Complete audio chunk
        """
        pass

    def synthesize_stream(self, text: str) -> Iterator[AudioChunk]:
        """Synthesize text with streaming output.
        
        Default implementation returns single chunk from synthesize().
        Override for backends with native streaming support.
        
        Args:
            text: Text to synthesize
            
        Yields:
            Audio chunks as they're generated
        """
        yield self.synthesize(text)

    def cleanup(self) -> None:
        """Release any resources held by the engine.
        
        Override in subclasses that need cleanup.
        """
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False

