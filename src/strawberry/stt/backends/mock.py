"""Mock STT engine for testing."""

from typing import Optional, Callable, List
import numpy as np

from ..base import STTEngine, TranscriptionResult


class MockSTT(STTEngine):
    """Mock STT engine for testing.
    
    Can be configured to return specific transcriptions or
    use a custom transcription function.
    """
    
    def __init__(
        self,
        sample_rate: int = 16000,
        default_text: str = "",
        transcription_fn: Optional[Callable[[np.ndarray], str]] = None,
        responses: Optional[List[str]] = None,
    ):
        """Initialize mock STT.
        
        Args:
            sample_rate: Simulated sample rate
            default_text: Default text to return if no other config
            transcription_fn: Custom function(audio) -> text
            responses: List of responses to return in order (cycles)
        """
        self._sample_rate = sample_rate
        self._default_text = default_text
        self._transcription_fn = transcription_fn
        self._responses = responses or []
        self._response_index = 0
        self._call_count = 0
        self._last_audio: Optional[np.ndarray] = None
    
    @property
    def sample_rate(self) -> int:
        return self._sample_rate
    
    def transcribe(self, audio: np.ndarray) -> TranscriptionResult:
        """Transcribe audio (mock implementation)."""
        self._call_count += 1
        self._last_audio = audio
        
        # Priority 1: Custom function
        if self._transcription_fn is not None:
            text = self._transcription_fn(audio)
            return TranscriptionResult(text=text, confidence=1.0)
        
        # Priority 2: Response list
        if self._responses:
            text = self._responses[self._response_index % len(self._responses)]
            self._response_index += 1
            return TranscriptionResult(text=text, confidence=1.0)
        
        # Priority 3: Default text
        return TranscriptionResult(text=self._default_text, confidence=1.0)
    
    def set_next_response(self, text: str) -> None:
        """Set the text to return on next transcribe() call."""
        self._responses = [text]
        self._response_index = 0
    
    def set_responses(self, responses: List[str]) -> None:
        """Set list of responses to cycle through."""
        self._responses = responses
        self._response_index = 0
    
    @property
    def call_count(self) -> int:
        """Number of times transcribe() was called."""
        return self._call_count
    
    @property
    def last_audio(self) -> Optional[np.ndarray]:
        """Last audio buffer passed to transcribe()."""
        return self._last_audio
    
    def reset(self) -> None:
        """Reset call count and response index."""
        self._call_count = 0
        self._response_index = 0
        self._last_audio = None

