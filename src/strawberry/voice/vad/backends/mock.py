"""Mock VAD backend for testing."""

from typing import Callable, Optional, Set

import numpy as np

from ..base import VADBackend


class MockVAD(VADBackend):
    """Mock VAD backend for testing.

    Can be configured to detect speech based on:
    - Specific frame indices (for deterministic testing)
    - Audio amplitude threshold
    - Custom detection function
    """

    # Module metadata for discovery
    name = "Mock VAD"
    description = "Mock VAD backend for testing. Returns configurable results."

    def __init__(
        self,
        sample_rate: int = 16000,
        speech_frames: Optional[Set[int]] = None,
        amplitude_threshold: Optional[int] = None,
        detector: Optional[Callable[[np.ndarray], bool]] = None,
    ):
        """Initialize mock VAD.

        Args:
            sample_rate: Expected audio sample rate
            speech_frames: Set of frame indices that should be detected as speech
            amplitude_threshold: If set, frames with max amplitude above this are speech
            detector: Custom function(frame) -> bool for speech detection
        """
        self._sample_rate = sample_rate
        self._speech_frames = speech_frames or set()
        self._amplitude_threshold = amplitude_threshold
        self._detector = detector
        self._frame_count = 0
        self._probability = 0.0  # Configurable probability for get_probability

    def is_speech(self, audio_frame: np.ndarray) -> bool:
        """Detect speech in frame."""
        frame_idx = self._frame_count
        self._frame_count += 1

        # Priority 1: Custom detector
        if self._detector is not None:
            result = self._detector(audio_frame)
            self._probability = 1.0 if result else 0.0
            return result

        # Priority 2: Specific frame indices
        if self._speech_frames:
            result = frame_idx in self._speech_frames
            self._probability = 1.0 if result else 0.0
            return result

        # Priority 3: Amplitude threshold
        if self._amplitude_threshold is not None:
            max_amp = np.max(np.abs(audio_frame))
            result = max_amp > self._amplitude_threshold
            self._probability = min(1.0, max_amp / 32767.0)
            return result

        # Default: no speech
        self._probability = 0.0
        return False

    def get_probability(self, audio_frame: np.ndarray) -> float:
        """Get speech probability.

        Note: Must call is_speech() first to update probability.
        """
        return self._probability

    def set_speech_frames(self, frames: Set[int]) -> None:
        """Update which frames are detected as speech."""
        self._speech_frames = frames

    def reset_frame_count(self) -> None:
        """Reset frame counter to 0."""
        self._frame_count = 0

    @property
    def frame_count(self) -> int:
        """Number of frames processed so far."""
        return self._frame_count
