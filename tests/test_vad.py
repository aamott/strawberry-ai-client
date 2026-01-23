"""Tests for VAD module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np

from strawberry.voice.vad.backends.mock import MockVAD
from strawberry.voice.vad.processor import VADConfig, VADProcessor


def make_frame(length: int = 480) -> np.ndarray:
    """Create a dummy audio frame."""
    return np.zeros(length, dtype=np.int16)


# --- VADConfig Tests ---

def test_vad_config_defaults():
    """VADConfig should have sensible defaults."""
    config = VADConfig()

    assert config.max_buffer == 2.0
    assert config.initial_buffer == 1.5
    assert config.base_decay == 1.0
    assert config.growth_rate == 2.0
    assert config.long_talk_threshold == 8.0


def test_vad_config_custom():
    """VADConfig should accept custom values."""
    config = VADConfig(
        max_buffer=3.0,
        initial_buffer=1.0,
        growth_rate=3.0,
    )

    assert config.max_buffer == 3.0
    assert config.initial_buffer == 1.0
    assert config.growth_rate == 3.0


# --- MockVAD Tests ---

def test_mock_vad_speech_frames():
    """MockVAD should detect speech for specified frame indices."""
    vad = MockVAD(speech_frames={0, 2, 4})
    frame = make_frame()

    assert vad.is_speech(frame)   # Frame 0
    assert not vad.is_speech(frame)  # Frame 1
    assert vad.is_speech(frame)   # Frame 2
    assert not vad.is_speech(frame)  # Frame 3
    assert vad.is_speech(frame)   # Frame 4


def test_mock_vad_amplitude_threshold():
    """MockVAD should detect speech based on amplitude."""
    vad = MockVAD(amplitude_threshold=1000)

    quiet_frame = np.array([100, -100, 50], dtype=np.int16)
    loud_frame = np.array([2000, -1500, 3000], dtype=np.int16)

    assert not vad.is_speech(quiet_frame)
    assert vad.is_speech(loud_frame)


def test_mock_vad_custom_detector():
    """MockVAD should use custom detector function."""
    # Detect speech if any sample > 500
    def detector(frame):
        return np.any(frame > 500)
    vad = MockVAD(detector=detector)

    no_speech = np.array([100, 200, 300], dtype=np.int16)
    has_speech = np.array([100, 600, 300], dtype=np.int16)

    assert not vad.is_speech(no_speech)
    assert vad.is_speech(has_speech)


def test_mock_vad_frame_count():
    """MockVAD should track processed frame count."""
    vad = MockVAD()
    frame = make_frame()

    assert vad.frame_count == 0
    vad.is_speech(frame)
    assert vad.frame_count == 1
    vad.is_speech(frame)
    vad.is_speech(frame)
    assert vad.frame_count == 3


# --- VADProcessor Tests ---

def test_processor_ends_on_silence():
    """Processor should end recording after sustained silence."""
    vad = MockVAD()  # No speech
    config = VADConfig(initial_buffer=0.1, base_decay=1.0)  # Fast drain
    processor = VADProcessor(vad, config, frame_duration_ms=30)
    processor.reset()

    frame = make_frame()

    # Process until it ends (or max iterations for safety)
    ended = False
    for _ in range(100):
        if processor.process(frame):
            ended = True
            break

    assert ended, "Recording should have ended"
    assert not processor.is_recording


def test_processor_continues_during_speech():
    """Processor should keep recording during continuous speech."""
    # All frames are speech
    vad = MockVAD(speech_frames=set(range(100)))
    config = VADConfig(initial_buffer=1.0, growth_rate=2.0)
    processor = VADProcessor(vad, config, frame_duration_ms=30)
    processor.reset()

    frame = make_frame()

    # Process many frames with speech
    ended = False
    for _ in range(50):
        if processor.process(frame):
            ended = True
            break

    assert not ended, "Recording should continue during speech"
    assert processor.counter > 0


def test_processor_buffer_caps_at_max():
    """Buffer should not exceed max_buffer."""
    vad = MockVAD(speech_frames=set(range(1000)))
    config = VADConfig(max_buffer=2.0, growth_rate=10.0)  # Fast fill
    processor = VADProcessor(vad, config, frame_duration_ms=30)
    processor.reset()

    frame = make_frame()

    # Process many speech frames
    for _ in range(100):
        processor.process(frame)

    assert processor.counter <= config.max_buffer


def test_processor_speech_then_silence():
    """Processor should end after speech followed by silence."""
    # Speech for first 10 frames, then silence
    vad = MockVAD(speech_frames=set(range(10)))
    config = VADConfig(
        initial_buffer=0.5,
        max_buffer=1.0,
        base_decay=1.0,
        growth_rate=2.0,
    )
    processor = VADProcessor(vad, config, frame_duration_ms=30)
    processor.reset()

    frame = make_frame()
    frames_until_end = 0

    for i in range(200):
        if processor.process(frame):
            frames_until_end = i
            break

    assert frames_until_end > 10, "Should end after speech period"
    assert processor.speech_detected, "Should have detected speech"


def test_processor_tracks_session_duration():
    """Processor should track session duration."""
    vad = MockVAD(speech_frames=set(range(100)))
    processor = VADProcessor(vad, frame_duration_ms=30)
    processor.reset()

    frame = make_frame()

    assert processor.session_duration == 0.0

    # Process 10 frames at 30ms each = 0.3 seconds
    for _ in range(10):
        processor.process(frame)

    assert abs(processor.session_duration - 0.3) < 0.001


def test_processor_aggressive_decay_after_threshold():
    """Decay should accelerate after long_talk_threshold."""
    vad = MockVAD()  # No speech
    config = VADConfig(
        initial_buffer=10.0,  # High buffer to last long
        base_decay=0.1,       # Slow base decay
        long_talk_threshold=0.1,  # Very short threshold
        decay_multiplier_rate=5.0,  # Aggressive multiplier
    )
    processor = VADProcessor(vad, config, frame_duration_ms=30)
    processor.reset()

    frame = make_frame()

    # Record counter after a few frames (before threshold)
    for _ in range(3):
        processor.process(frame)
    counter_early = processor.counter

    # Process many more frames (after threshold)
    for _ in range(50):
        processor.process(frame)
    counter_late = processor.counter

    # Counter should have dropped significantly due to multiplier
    assert counter_late < counter_early


def test_processor_force_stop():
    """force_stop() should immediately end recording."""
    vad = MockVAD(speech_frames=set(range(100)))
    processor = VADProcessor(vad)
    processor.reset()

    frame = make_frame()

    # Start processing
    processor.process(frame)
    assert processor.is_recording

    # Force stop
    processor.force_stop()

    assert not processor.is_recording
    assert processor.counter == 0.0


def test_processor_speech_detected_flag():
    """speech_detected should be True only if speech occurred."""
    # No speech
    vad = MockVAD()
    processor = VADProcessor(vad, VADConfig(initial_buffer=0.1))
    processor.reset()

    frame = make_frame()
    while not processor.process(frame):
        pass

    assert not processor.speech_detected

    # With speech
    vad = MockVAD(speech_frames={0, 1})
    processor = VADProcessor(vad, VADConfig(initial_buffer=0.1))
    processor.reset()

    processor.process(frame)  # Frame 0 - speech

    assert processor.speech_detected


def test_processor_reset_clears_state():
    """reset() should clear all state."""
    vad = MockVAD(speech_frames={0})
    processor = VADProcessor(vad)
    processor.reset()

    frame = make_frame()
    processor.process(frame)  # Detect speech
    processor.force_stop()

    # State after force_stop
    assert not processor.is_recording
    assert processor.counter == 0.0

    # Reset
    processor.reset()

    assert processor.is_recording
    assert processor.counter == processor.config.initial_buffer
    assert processor.session_duration == 0.0
    assert not processor.speech_detected

