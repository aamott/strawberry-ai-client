"""Tests for wake word detection module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np

from strawberry.voice.wakeword.backends.mock import MockWakeWordDetector


def make_frame(length: int = 512) -> np.ndarray:
    """Create a dummy audio frame."""
    return np.zeros(length, dtype=np.int16)


# --- MockWakeWordDetector Tests ---

def test_mock_detector_properties():
    """Mock detector should expose correct properties."""
    detector = MockWakeWordDetector(
        keywords=["hello", "goodbye"],
        sample_rate=16000,
        frame_length=512,
    )

    assert detector.keywords == ["hello", "goodbye"]
    assert detector.sample_rate == 16000
    assert detector.frame_length == 512


def test_mock_detector_no_trigger_by_default():
    """Mock detector should not trigger without configuration."""
    detector = MockWakeWordDetector()
    frame = make_frame()

    # Process several frames
    for _ in range(10):
        result = detector.process(frame)
        assert result == -1, "Should not trigger without configuration"


def test_mock_detector_trigger_frames():
    """Mock detector should trigger on specified frame indices."""
    detector = MockWakeWordDetector(trigger_frames={2, 5})
    frame = make_frame()

    results = [detector.process(frame) for _ in range(7)]

    assert results == [-1, -1, 0, -1, -1, 0, -1]


def test_mock_detector_trigger_on_next():
    """trigger_on_next() should queue a detection."""
    detector = MockWakeWordDetector(keywords=["word1", "word2"])
    frame = make_frame()

    # No trigger initially
    assert detector.process(frame) == -1

    # Queue trigger for keyword index 1
    detector.trigger_on_next(keyword_index=1)

    # Next process should return 1
    assert detector.process(frame) == 1

    # Back to no trigger
    assert detector.process(frame) == -1


def test_mock_detector_multiple_queued_triggers():
    """Multiple triggers can be queued."""
    detector = MockWakeWordDetector(keywords=["a", "b", "c"])
    frame = make_frame()

    detector.trigger_on_next(0)
    detector.trigger_on_next(2)
    detector.trigger_on_next(1)

    assert detector.process(frame) == 0
    assert detector.process(frame) == 2
    assert detector.process(frame) == 1
    assert detector.process(frame) == -1


def test_mock_detector_frame_count():
    """Mock detector should track frame count."""
    detector = MockWakeWordDetector()
    frame = make_frame()

    assert detector.frame_count == 0

    detector.process(frame)
    detector.process(frame)
    detector.process(frame)

    assert detector.frame_count == 3


def test_mock_detector_reset():
    """reset_frame_count() should reset state."""
    detector = MockWakeWordDetector(trigger_frames={0})
    frame = make_frame()

    # Process past trigger frame
    detector.process(frame)  # Frame 0 - triggers
    detector.process(frame)  # Frame 1

    assert detector.frame_count == 2

    # Reset
    detector.reset_frame_count()

    assert detector.frame_count == 0

    # Frame 0 should trigger again
    assert detector.process(frame) == 0


def test_mock_detector_context_manager():
    """Mock detector should work as context manager."""
    with MockWakeWordDetector() as detector:
        frame = make_frame()
        result = detector.process(frame)
        assert result == -1


def test_mock_detector_set_trigger_frames():
    """set_trigger_frames() should update trigger configuration."""
    detector = MockWakeWordDetector()
    frame = make_frame()

    # Initially no triggers
    assert detector.process(frame) == -1  # Frame 0
    assert detector.process(frame) == -1  # Frame 1

    # Set new trigger frames
    detector.set_trigger_frames({2, 3})

    assert detector.process(frame) == 0  # Frame 2 - triggers
    assert detector.process(frame) == 0  # Frame 3 - triggers
    assert detector.process(frame) == -1  # Frame 4


def test_mock_detector_default_keywords():
    """Mock detector should have default keyword if none provided."""
    detector = MockWakeWordDetector()

    assert len(detector.keywords) > 0
    assert detector.keywords == ["test_wake_word"]


# --- Integration-style Tests ---

def test_wake_word_with_audio_stream_pattern():
    """Test wake word detection in a realistic usage pattern."""
    detector = MockWakeWordDetector(
        keywords=["jarvis"],
        trigger_frames={50},  # Trigger at frame 50
    )

    frame = make_frame(detector.frame_length)

    wake_detected = False
    wake_keyword = None

    for i in range(100):
        result = detector.process(frame)
        if result >= 0:
            wake_detected = True
            wake_keyword = detector.keywords[result]
            break

    assert wake_detected, "Should have detected wake word"
    assert wake_keyword == "jarvis"
    assert detector.frame_count == 51  # Processed 51 frames (0-50 inclusive)

