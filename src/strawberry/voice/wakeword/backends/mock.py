"""Mock wake word detector for testing."""

from typing import List, Optional, Set

import numpy as np

from ..base import WakeWordDetector


class MockWakeWordDetector(WakeWordDetector):
    """Mock wake word detector for testing.

    Can be configured to trigger on specific frame indices
    or programmatically via trigger_on_next().
    """

    # Module metadata for discovery
    name = "Mock Wake Word"
    description = "Mock wake word detector for testing. Returns configurable results."

    def __init__(
        self,
        keywords: List[str] = None,
        sensitivity: float = 0.5,
        trigger_frames: Optional[Set[int]] = None,
        sample_rate: int = 16000,
        frame_length: int = 512,
    ):
        """Initialize mock detector.

        Args:
            keywords: List of wake words (for interface compatibility)
            sensitivity: Detection sensitivity (unused in mock)
            trigger_frames: Set of frame indices that should trigger detection
            sample_rate: Simulated sample rate
            frame_length: Simulated frame length in samples
        """
        self._keywords = keywords or ["test_wake_word"]
        self._sensitivity = sensitivity
        self._trigger_frames = trigger_frames or set()
        self._sample_rate = sample_rate
        self._frame_length = frame_length
        self._frame_count = 0
        self._pending_triggers: List[int] = []  # Keyword indices to return

    @property
    def keywords(self) -> List[str]:
        return self._keywords

    @property
    def frame_length(self) -> int:
        return self._frame_length

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def process(self, audio_frame: np.ndarray) -> int:
        """Process frame for wake word detection.

        Returns:
            Keyword index if triggered, -1 otherwise
        """
        frame_idx = self._frame_count
        self._frame_count += 1

        # Check for pending manual triggers
        if self._pending_triggers:
            return self._pending_triggers.pop(0)

        # Check for frame-based triggers
        if frame_idx in self._trigger_frames:
            return 0  # Return first keyword index

        return -1

    def trigger_on_next(self, keyword_index: int = 0) -> None:
        """Queue a trigger for the next process() call.

        Args:
            keyword_index: Index of keyword to simulate detecting
        """
        self._pending_triggers.append(keyword_index)

    def set_trigger_frames(self, frames: Set[int]) -> None:
        """Set which frames should trigger detection."""
        self._trigger_frames = frames

    def reset_frame_count(self) -> None:
        """Reset frame counter to 0."""
        self._frame_count = 0
        self._pending_triggers = []

    @property
    def frame_count(self) -> int:
        """Number of frames processed so far."""
        return self._frame_count
