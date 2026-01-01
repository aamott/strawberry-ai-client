"""Tests for Speech-to-Text module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np

from strawberry.stt.backends.mock import MockSTT
from strawberry.stt.base import TranscriptionResult


def make_audio(duration_sec: float = 1.0, sample_rate: int = 16000) -> np.ndarray:
    """Create dummy audio data."""
    num_samples = int(duration_sec * sample_rate)
    return np.zeros(num_samples, dtype=np.int16)


# --- TranscriptionResult Tests ---

def test_transcription_result_defaults():
    """TranscriptionResult should have sensible defaults."""
    result = TranscriptionResult(text="hello world")

    assert result.text == "hello world"
    assert result.confidence == 1.0
    assert result.is_final == True
    assert result.words is None
    assert result.language is None


def test_transcription_result_with_words():
    """TranscriptionResult should store word-level data."""
    words = [
        {"word": "hello", "start_sec": 0.0, "end_sec": 0.5},
        {"word": "world", "start_sec": 0.5, "end_sec": 1.0},
    ]
    result = TranscriptionResult(
        text="hello world",
        confidence=0.95,
        words=words,
    )

    assert len(result.words) == 2
    assert result.words[0]["word"] == "hello"


# --- MockSTT Tests ---

def test_mock_stt_default_response():
    """MockSTT should return default text."""
    stt = MockSTT(default_text="default response")
    audio = make_audio()

    result = stt.transcribe(audio)

    assert result.text == "default response"
    assert result.is_final == True


def test_mock_stt_empty_default():
    """MockSTT should return empty string by default."""
    stt = MockSTT()
    audio = make_audio()

    result = stt.transcribe(audio)

    assert result.text == ""


def test_mock_stt_set_next_response():
    """set_next_response() should set next transcription."""
    stt = MockSTT()
    audio = make_audio()

    stt.set_next_response("hello there")
    result = stt.transcribe(audio)

    assert result.text == "hello there"


def test_mock_stt_response_list():
    """MockSTT should cycle through response list."""
    stt = MockSTT(responses=["one", "two", "three"])
    audio = make_audio()

    results = [stt.transcribe(audio).text for _ in range(5)]

    assert results == ["one", "two", "three", "one", "two"]


def test_mock_stt_custom_function():
    """MockSTT should use custom transcription function."""
    # Return text based on audio length
    def custom_fn(audio):
        return f"audio_length:{len(audio)}"

    stt = MockSTT(transcription_fn=custom_fn)

    short_audio = make_audio(0.5)
    long_audio = make_audio(2.0)

    assert stt.transcribe(short_audio).text == "audio_length:8000"
    assert stt.transcribe(long_audio).text == "audio_length:32000"


def test_mock_stt_call_count():
    """MockSTT should track call count."""
    stt = MockSTT()
    audio = make_audio()

    assert stt.call_count == 0

    stt.transcribe(audio)
    stt.transcribe(audio)
    stt.transcribe(audio)

    assert stt.call_count == 3


def test_mock_stt_stores_last_audio():
    """MockSTT should store last audio buffer."""
    stt = MockSTT()

    audio1 = np.array([1, 2, 3], dtype=np.int16)
    audio2 = np.array([4, 5, 6, 7], dtype=np.int16)

    stt.transcribe(audio1)
    assert np.array_equal(stt.last_audio, audio1)

    stt.transcribe(audio2)
    assert np.array_equal(stt.last_audio, audio2)


def test_mock_stt_reset():
    """reset() should clear state."""
    stt = MockSTT(responses=["a", "b", "c"])
    audio = make_audio()

    stt.transcribe(audio)  # "a"
    stt.transcribe(audio)  # "b"

    assert stt.call_count == 2

    stt.reset()

    assert stt.call_count == 0
    assert stt.last_audio is None
    assert stt.transcribe(audio).text == "a"  # Back to first response


def test_mock_stt_sample_rate():
    """MockSTT should report configured sample rate."""
    stt = MockSTT(sample_rate=48000)

    assert stt.sample_rate == 48000


def test_mock_stt_context_manager():
    """MockSTT should work as context manager."""
    with MockSTT(default_text="test") as stt:
        result = stt.transcribe(make_audio())
        assert result.text == "test"


# --- Integration Pattern Tests ---

def test_stt_with_vad_output_pattern():
    """Test STT with typical VAD output (concatenated audio)."""
    stt = MockSTT(default_text="turn on the lights")

    # Simulate VAD collecting frames then concatenating
    frames = [make_audio(0.03) for _ in range(50)]  # 50 frames @ 30ms = 1.5s
    combined_audio = np.concatenate(frames)

    result = stt.transcribe(combined_audio)

    assert result.text == "turn on the lights"
    assert len(stt.last_audio) == sum(len(f) for f in frames)

