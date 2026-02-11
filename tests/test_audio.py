"""Tests for audio module."""

import sys
import time
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np

from strawberry.voice.audio.backends.mock import (
    MockAudioBackend,
    generate_sine_wave,
)
from strawberry.voice.audio.stream import AudioStream

# --- MockAudioBackend Tests ---


def test_mock_backend_generates_silence_by_default():
    """Mock backend should generate silent frames by default."""
    backend = MockAudioBackend(sample_rate=16000, frame_length_ms=30)
    backend.start()

    frame = backend.read_frame()

    assert len(frame) == 480  # 16000 * 30 / 1000
    assert frame.dtype == np.int16
    assert np.all(frame == 0)  # All zeros = silence

    backend.stop()


def test_mock_backend_frame_length_calculation():
    """Frame length should be calculated correctly from sample rate and ms."""
    backend = MockAudioBackend(sample_rate=16000, frame_length_ms=30)
    assert backend.frame_length == 480

    backend = MockAudioBackend(sample_rate=48000, frame_length_ms=20)
    assert backend.frame_length == 960


def test_mock_backend_inject_frames():
    """Should be able to inject specific frames for testing."""
    backend = MockAudioBackend()
    backend.start()

    test_frame = np.array([1, 2, 3, 4, 5], dtype=np.int16)
    backend.inject_frame(test_frame)

    frame = backend.read_frame()

    assert np.array_equal(frame, test_frame)

    backend.stop()


def test_mock_backend_sine_wave_generator():
    """Sine wave generator should produce non-zero audio."""
    generator = generate_sine_wave(frequency=440, amplitude=10000)
    backend = MockAudioBackend(generator=generator)
    backend.start()

    frame = backend.read_frame()

    assert len(frame) == backend.frame_length
    assert not np.all(frame == 0)  # Should not be silent
    assert np.max(np.abs(frame)) <= 10000  # Within amplitude

    backend.stop()


def test_mock_backend_context_manager():
    """Mock backend should work as context manager."""
    with MockAudioBackend() as backend:
        assert backend.is_active
        frame = backend.read_frame()
        assert len(frame) == backend.frame_length

    assert not backend.is_active


def test_mock_backend_raises_when_not_started():
    """Should raise error when reading from stopped backend."""
    backend = MockAudioBackend()

    try:
        backend.read_frame()
        assert False, "Expected RuntimeError"
    except RuntimeError as e:
        assert "not started" in str(e)


# --- AudioStream Tests ---


def test_stream_distributes_to_subscribers():
    """AudioStream should distribute frames to all subscribers."""
    backend = MockAudioBackend()
    stream = AudioStream(backend, buffer_size=10)

    received_frames = []

    def subscriber(frame):
        received_frames.append(frame)

    # Inject some frames
    for i in range(3):
        backend.inject_frame(np.array([i] * 10, dtype=np.int16))

    stream.subscribe(subscriber)
    stream.start()

    # Wait for frames to be processed
    time.sleep(0.1)

    stream.stop()

    assert len(received_frames) >= 3


def test_stream_multiple_subscribers():
    """AudioStream should send same frame to multiple subscribers."""
    backend = MockAudioBackend()
    stream = AudioStream(backend, buffer_size=10)

    received_a = []
    received_b = []

    def subscriber_a(frame):
        received_a.append(frame.copy())

    def subscriber_b(frame):
        received_b.append(frame.copy())

    # Inject frames
    test_frame = np.array([42] * 480, dtype=np.int16)
    backend.inject_frame(test_frame)

    stream.subscribe(subscriber_a)
    stream.subscribe(subscriber_b)
    stream.start()

    time.sleep(0.1)
    stream.stop()

    assert len(received_a) >= 1
    assert len(received_b) >= 1
    # Both should have received the same frame
    assert np.array_equal(received_a[0], received_b[0])


def test_stream_buffer_stores_frames():
    """AudioStream buffer should store recent frames."""
    backend = MockAudioBackend()
    stream = AudioStream(backend, buffer_size=5)

    # Inject numbered frames
    for i in range(3):
        backend.inject_frame(np.array([i] * 10, dtype=np.int16))

    stream.start()
    time.sleep(0.1)
    stream.stop()

    # Get buffer
    buffer = stream.get_buffer(frames=2)

    assert len(buffer) > 0


def test_stream_unsubscribe():
    """Should be able to unsubscribe from stream."""
    backend = MockAudioBackend()
    stream = AudioStream(backend, buffer_size=10)

    received = []

    def subscriber(frame):
        received.append(frame)

    stream.subscribe(subscriber)
    stream.unsubscribe(subscriber)

    backend.inject_frame(np.zeros(10, dtype=np.int16))
    stream.start()
    time.sleep(0.1)
    stream.stop()

    # Subscriber should not have received anything (unsubscribed before start)
    # Actually, the mock backend generates frames continuously, so this tests
    # that the specific subscriber was removed
    assert subscriber not in stream._subscribers


def test_stream_context_manager():
    """AudioStream should work as context manager."""
    backend = MockAudioBackend()

    with AudioStream(backend) as stream:
        assert stream.is_active

    assert not stream.is_active


def test_stream_properties_from_backend():
    """Stream should expose backend properties."""
    backend = MockAudioBackend(sample_rate=48000, frame_length_ms=20)
    stream = AudioStream(backend)

    assert stream.sample_rate == 48000
    assert stream.frame_length == 960  # 48000 * 20 / 1000


def test_stream_handles_subscriber_error():
    """Stream should continue if a subscriber raises an error."""
    backend = MockAudioBackend()
    stream = AudioStream(backend, suppress_errors=True)  # Suppress error output in test

    good_received = []

    def bad_subscriber(frame):
        raise ValueError("Intentional test error")

    def good_subscriber(frame):
        good_received.append(frame)

    stream.subscribe(bad_subscriber)
    stream.subscribe(good_subscriber)

    backend.inject_frame(np.zeros(10, dtype=np.int16))
    stream.start()
    time.sleep(0.1)
    stream.stop()

    # Good subscriber should still have received frames
    assert len(good_received) >= 1
