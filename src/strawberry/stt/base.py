"""Abstract base class for Speech-to-Text engines."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

import numpy as np


@dataclass
class TranscriptionResult:
    """Result from STT processing.
    
    Attributes:
        text: The transcribed text
        confidence: Confidence score (0.0 to 1.0), if available
        is_final: Whether this is a final result or interim
        words: Optional list of word-level results with timing
        language: Detected language code, if available
    """
    text: str
    confidence: float = 1.0
    is_final: bool = True
    words: Optional[List[dict]] = None
    language: Optional[str] = None


class STTEngine(ABC):
    """Abstract base class for Speech-to-Text engines.
    
    All STT backends must implement this interface.
    """

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Required audio sample rate in Hz."""
        pass

    @abstractmethod
    def transcribe(self, audio: np.ndarray) -> TranscriptionResult:
        """Transcribe complete audio buffer.
        
        Args:
            audio: Complete audio buffer (int16)
            
        Returns:
            Transcription result
        """
        pass

    def transcribe_file(self, file_path: str) -> TranscriptionResult:
        """Transcribe audio from file.
        
        Default implementation reads file and calls transcribe().
        Override for backends with native file support.
        
        Args:
            file_path: Path to audio file
            
        Returns:
            Transcription result
        """
        import wave

        with wave.open(file_path, 'rb') as wf:
            audio = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)

        return self.transcribe(audio)

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

