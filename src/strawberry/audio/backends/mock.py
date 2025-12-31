"""Mock audio backend for testing without hardware."""

from typing import Optional, Callable
import numpy as np
import queue
import time

from ..base import AudioBackend


class MockAudioBackend(AudioBackend):
    """Mock audio backend for testing.
    
    Generates synthetic audio frames without requiring real hardware.
    Can be configured to generate silence, noise, or custom patterns.
    """
    
    def __init__(
        self,
        sample_rate: int = 16000,
        frame_length_ms: int = 30,
        generator: Optional[Callable[[int, int], np.ndarray]] = None,
    ):
        """Initialize mock backend.
        
        Args:
            sample_rate: Audio sample rate in Hz
            frame_length_ms: Length of each audio frame in milliseconds
            generator: Optional function(frame_length, frame_index) -> np.ndarray
                      If None, generates silence
        """
        super().__init__(sample_rate, frame_length_ms)
        self._generator = generator or self._generate_silence
        self._active = False
        self._frame_index = 0
        self._queue: queue.Queue = queue.Queue()
        self._injected_frames: list[np.ndarray] = []
    
    def _generate_silence(self, frame_length: int, frame_index: int) -> np.ndarray:
        """Generate silent audio frame."""
        return np.zeros(frame_length, dtype=np.int16)
    
    def inject_frame(self, frame: np.ndarray) -> None:
        """Inject a specific frame to be returned by next read.
        
        Useful for testing specific audio patterns.
        """
        self._injected_frames.append(frame)
    
    def inject_frames(self, frames: list[np.ndarray]) -> None:
        """Inject multiple frames."""
        self._injected_frames.extend(frames)
    
    def start(self) -> None:
        """Start the mock stream."""
        self._active = True
        self._frame_index = 0
    
    def stop(self) -> None:
        """Stop the mock stream."""
        self._active = False
    
    def read_frame(self) -> np.ndarray:
        """Read a single audio frame.
        
        Returns injected frames first, then generated frames.
        """
        if not self._active:
            raise RuntimeError("Audio stream not started")
        
        # Return injected frames first
        if self._injected_frames:
            return self._injected_frames.pop(0)
        
        # Generate a frame
        frame = self._generator(self.frame_length, self._frame_index)
        self._frame_index += 1
        
        # Small delay to simulate real audio timing
        time.sleep(self.frame_length_ms / 1000.0 * 0.1)  # 10% of frame time
        
        return frame
    
    @property
    def is_active(self) -> bool:
        """Check if stream is currently active."""
        return self._active


def generate_sine_wave(
    frequency: float = 440.0,
    amplitude: int = 10000,
    sample_rate: int = 16000,
) -> Callable[[int, int], np.ndarray]:
    """Create a generator function that produces sine wave audio.
    
    Args:
        frequency: Frequency in Hz
        amplitude: Peak amplitude (0-32767 for int16)
        sample_rate: Audio sample rate
        
    Returns:
        Generator function for use with MockAudioBackend
    """
    def generator(frame_length: int, frame_index: int) -> np.ndarray:
        start_sample = frame_index * frame_length
        t = np.arange(start_sample, start_sample + frame_length) / sample_rate
        wave = amplitude * np.sin(2 * np.pi * frequency * t)
        return wave.astype(np.int16)
    
    return generator


def generate_noise(amplitude: int = 5000) -> Callable[[int, int], np.ndarray]:
    """Create a generator function that produces random noise.
    
    Args:
        amplitude: Peak amplitude
        
    Returns:
        Generator function for use with MockAudioBackend
    """
    def generator(frame_length: int, frame_index: int) -> np.ndarray:
        return np.random.randint(-amplitude, amplitude, frame_length, dtype=np.int16)
    
    return generator

