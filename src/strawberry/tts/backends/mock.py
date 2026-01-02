"""Mock TTS engine for testing."""

from typing import Callable, Iterator, List, Optional

import numpy as np

from ..base import AudioChunk, TTSEngine


class MockTTS(TTSEngine):
    """Mock TTS engine for testing.

    Can be configured to return silence, sine waves, or custom audio.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        audio_generator: Optional[Callable[[str], np.ndarray]] = None,
        words_per_second: float = 2.5,  # For calculating duration
    ):
        """Initialize mock TTS.

        Args:
            sample_rate: Output sample rate
            audio_generator: Custom function(text) -> np.ndarray
            words_per_second: Used to estimate audio duration from text length
        """
        self._sample_rate = sample_rate
        self._audio_generator = audio_generator
        self._words_per_second = words_per_second
        self._call_count = 0
        self._last_text: Optional[str] = None
        self._synthesized_texts: List[str] = []

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def synthesize(self, text: str) -> AudioChunk:
        """Synthesize text to audio (mock implementation)."""
        self._call_count += 1
        self._last_text = text
        self._synthesized_texts.append(text)

        # Use custom generator if provided
        if self._audio_generator is not None:
            audio = self._audio_generator(text)
            return AudioChunk(audio=audio, sample_rate=self._sample_rate)

        # Generate silence based on estimated duration
        duration = self._estimate_duration(text)
        num_samples = int(duration * self._sample_rate)
        audio = np.zeros(num_samples, dtype=np.int16)

        return AudioChunk(audio=audio, sample_rate=self._sample_rate)

    def synthesize_stream(self, text: str) -> Iterator[AudioChunk]:
        """Synthesize with simulated streaming."""
        self._call_count += 1
        self._last_text = text
        self._synthesized_texts.append(text)

        # Split text into words and yield chunks
        words = text.split()
        if not words:
            return

        for word in words:
            duration = 1.0 / self._words_per_second
            num_samples = int(duration * self._sample_rate)

            if self._audio_generator:
                audio = self._audio_generator(word)
            else:
                audio = np.zeros(num_samples, dtype=np.int16)

            yield AudioChunk(audio=audio, sample_rate=self._sample_rate)

    def _estimate_duration(self, text: str) -> float:
        """Estimate audio duration from text."""
        words = len(text.split())
        return max(0.1, words / self._words_per_second)

    @property
    def call_count(self) -> int:
        """Number of times synthesize/synthesize_stream was called."""
        return self._call_count

    @property
    def last_text(self) -> Optional[str]:
        """Last text passed to synthesize."""
        return self._last_text

    @property
    def synthesized_texts(self) -> List[str]:
        """All texts synthesized so far."""
        return self._synthesized_texts

    def reset(self) -> None:
        """Reset state."""
        self._call_count = 0
        self._last_text = None
        self._synthesized_texts = []


def generate_tone_audio(
    frequency: float = 440.0,
    amplitude: int = 10000,
    sample_rate: int = 16000,
    duration_per_char: float = 0.05,
) -> Callable[[str], np.ndarray]:
    """Create generator that produces tone audio based on text length.

    Args:
        frequency: Tone frequency in Hz
        amplitude: Peak amplitude
        sample_rate: Sample rate
        duration_per_char: Duration per character in seconds

    Returns:
        Function(text) -> np.ndarray for use with MockTTS
    """
    def generator(text: str) -> np.ndarray:
        duration = len(text) * duration_per_char
        num_samples = int(duration * sample_rate)
        t = np.arange(num_samples) / sample_rate
        wave = amplitude * np.sin(2 * np.pi * frequency * t)
        return wave.astype(np.int16)

    return generator

