"""Tests for Text-to-Speech module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np

from strawberry.tts.backends.mock import MockTTS, generate_tone_audio
from strawberry.tts.base import AudioChunk

# --- AudioChunk Tests ---

def test_audio_chunk_duration():
    """AudioChunk should calculate duration correctly."""
    # 16000 samples at 16000 Hz = 1 second
    audio = np.zeros(16000, dtype=np.int16)
    chunk = AudioChunk(audio=audio, sample_rate=16000)

    assert chunk.duration_sec == 1.0


def test_audio_chunk_duration_fractional():
    """AudioChunk should handle fractional durations."""
    # 8000 samples at 16000 Hz = 0.5 seconds
    audio = np.zeros(8000, dtype=np.int16)
    chunk = AudioChunk(audio=audio, sample_rate=16000)

    assert chunk.duration_sec == 0.5


# --- MockTTS Tests ---

def test_mock_tts_synthesize_basic():
    """MockTTS should synthesize text to audio."""
    tts = MockTTS(sample_rate=16000)

    chunk = tts.synthesize("hello world")

    assert chunk.sample_rate == 16000
    assert len(chunk.audio) > 0
    assert chunk.audio.dtype == np.int16


def test_mock_tts_duration_based_on_words():
    """MockTTS should generate longer audio for more words."""
    tts = MockTTS(words_per_second=2.0)

    short = tts.synthesize("hi")
    long = tts.synthesize("hello there my friend how are you")

    assert long.duration_sec > short.duration_sec


def test_mock_tts_custom_generator():
    """MockTTS should use custom audio generator."""
    def generator(text):
        # Return array with length = text length
        return np.ones(len(text), dtype=np.int16)

    tts = MockTTS(audio_generator=generator)

    chunk = tts.synthesize("hello")  # 5 chars

    assert len(chunk.audio) == 5


def test_mock_tts_call_count():
    """MockTTS should track synthesis calls."""
    tts = MockTTS()

    assert tts.call_count == 0

    tts.synthesize("one")
    tts.synthesize("two")

    assert tts.call_count == 2


def test_mock_tts_last_text():
    """MockTTS should store last synthesized text."""
    tts = MockTTS()

    tts.synthesize("first message")
    assert tts.last_text == "first message"

    tts.synthesize("second message")
    assert tts.last_text == "second message"


def test_mock_tts_synthesized_texts():
    """MockTTS should store all synthesized texts."""
    tts = MockTTS()

    tts.synthesize("one")
    tts.synthesize("two")
    tts.synthesize("three")

    assert tts.synthesized_texts == ["one", "two", "three"]


def test_mock_tts_stream():
    """MockTTS should support streaming synthesis."""
    tts = MockTTS(words_per_second=2.0)

    chunks = list(tts.synthesize_stream("hello world how are you"))

    # Should yield one chunk per word
    assert len(chunks) == 5
    for chunk in chunks:
        assert chunk.sample_rate == tts.sample_rate
        assert len(chunk.audio) > 0


def test_mock_tts_stream_empty():
    """MockTTS stream should handle empty text."""
    tts = MockTTS()

    chunks = list(tts.synthesize_stream(""))

    assert len(chunks) == 0


def test_mock_tts_stream_counts_as_call():
    """synthesize_stream should increment call count."""
    tts = MockTTS()

    list(tts.synthesize_stream("hello"))

    assert tts.call_count == 1
    assert tts.last_text == "hello"


def test_mock_tts_reset():
    """reset() should clear state."""
    tts = MockTTS()

    tts.synthesize("one")
    tts.synthesize("two")

    assert tts.call_count == 2

    tts.reset()

    assert tts.call_count == 0
    assert tts.last_text is None
    assert tts.synthesized_texts == []


def test_mock_tts_sample_rate():
    """MockTTS should report configured sample rate."""
    tts = MockTTS(sample_rate=48000)

    assert tts.sample_rate == 48000


def test_mock_tts_context_manager():
    """MockTTS should work as context manager."""
    with MockTTS() as tts:
        chunk = tts.synthesize("test")
        assert len(chunk.audio) > 0


# --- Generator Helper Tests ---

def test_generate_tone_audio():
    """generate_tone_audio should create tone generator."""
    generator = generate_tone_audio(
        frequency=440,
        amplitude=10000,
        sample_rate=16000,
        duration_per_char=0.1,
    )

    audio = generator("hello")  # 5 chars * 0.1 = 0.5 sec

    # 0.5 sec at 16000 Hz = 8000 samples
    assert len(audio) == 8000
    assert audio.dtype == np.int16
    assert np.max(np.abs(audio)) <= 10000


def test_mock_tts_with_tone_generator():
    """MockTTS should work with tone generator."""
    generator = generate_tone_audio(frequency=440)
    tts = MockTTS(audio_generator=generator)

    chunk = tts.synthesize("testing")

    # Should have non-zero audio (sine wave)
    assert np.any(chunk.audio != 0)


# --- Integration Pattern Tests ---

def test_tts_playback_pattern():
    """Test TTS in typical playback pattern."""
    tts = MockTTS(words_per_second=2.0)

    response_text = "I have turned on the lights for you."

    # Non-streaming
    chunk = tts.synthesize(response_text)
    assert chunk.duration_sec > 0

    # Streaming
    tts.reset()
    total_duration = 0
    for chunk in tts.synthesize_stream(response_text):
        total_duration += chunk.duration_sec

    assert total_duration > 0

