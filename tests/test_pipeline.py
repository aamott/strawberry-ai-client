"""Tests for conversation pipeline."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from strawberry.voice.audio.backends.mock import MockAudioBackend
from strawberry.voice.pipeline.conversation import (
    ConversationPipeline,
    PipelineConfig,
    PipelineState,
)
from strawberry.voice.pipeline.events import EventType
from strawberry.voice.stt.backends.mock import MockSTT
from strawberry.voice.tts.backends.mock import MockTTS
from strawberry.voice.vad.backends.mock import MockVAD
from strawberry.voice.vad.processor import VADConfig
from strawberry.voice.wakeword.backends.mock import MockWakeWordDetector


def create_pipeline(
    wake_trigger_frames=None,
    speech_frames=None,
    stt_response="hello world",
    response_handler=None,
    vad_config=None,
):
    """Helper to create a test pipeline with mocks."""
    audio = MockAudioBackend(sample_rate=16000, frame_length_ms=30)
    wake = MockWakeWordDetector(
        keywords=["jarvis"],
        trigger_frames=wake_trigger_frames or set(),
    )
    vad = MockVAD(speech_frames=speech_frames or set())
    stt = MockSTT(default_text=stt_response)
    tts = MockTTS(words_per_second=10.0)  # Fast for testing

    config = PipelineConfig(
        max_recording_duration=5.0,
        lookback_frames=5,
        vad_config=vad_config or VADConfig(initial_buffer=0.1, base_decay=2.0),
    )

    return ConversationPipeline(
        audio_backend=audio,
        wake_detector=wake,
        vad_backend=vad,
        stt_engine=stt,
        tts_engine=tts,
        response_handler=response_handler,
        config=config,
    )


# --- State Tests ---

def test_pipeline_initial_state():
    """Pipeline should start in IDLE state."""
    pipeline = create_pipeline()

    assert pipeline.state == PipelineState.IDLE


def test_pipeline_start_transitions_to_listening():
    """start() should transition to LISTENING state."""
    pipeline = create_pipeline()

    pipeline.start()

    assert pipeline.state == PipelineState.LISTENING

    pipeline.stop()


def test_pipeline_stop_transitions_to_idle():
    """stop() should transition to IDLE state."""
    pipeline = create_pipeline()
    pipeline.start()

    pipeline.stop()

    assert pipeline.state == PipelineState.IDLE


def test_pipeline_pause_and_resume():
    """pause() and resume() should work correctly."""
    pipeline = create_pipeline()
    pipeline.start()

    assert pipeline.state == PipelineState.LISTENING

    pipeline.pause()
    assert pipeline.state == PipelineState.PAUSED

    pipeline.resume()
    assert pipeline.state == PipelineState.LISTENING

    pipeline.stop()


# --- Event Tests ---

def test_pipeline_emits_state_changed_events():
    """Pipeline should emit STATE_CHANGED events."""
    pipeline = create_pipeline()
    events = []

    pipeline.on_event(lambda e: events.append(e))
    pipeline.start()
    pipeline.stop()

    state_events = [e for e in events if e.type == EventType.STATE_CHANGED]
    assert len(state_events) >= 2  # At least start and stop


def test_pipeline_emits_wake_word_event():
    """Pipeline should emit WAKE_WORD_DETECTED when triggered."""
    # Wake word at frame 5
    pipeline = create_pipeline(wake_trigger_frames={5})
    events = []

    pipeline.on_event(lambda e: events.append(e))
    pipeline.start()

    # Wait for wake word to be processed
    time.sleep(0.2)

    pipeline.stop()

    wake_events = [e for e in events if e.type == EventType.WAKE_WORD_DETECTED]
    assert len(wake_events) >= 1
    assert wake_events[0].data["keyword"] == "jarvis"


# --- Text Processing Tests ---

def test_pipeline_process_text():
    """process_text() should bypass audio and return response."""
    pipeline = create_pipeline(
        response_handler=lambda x: f"Response to: {x}"
    )

    response = pipeline.process_text("turn on the lights")

    assert response == "Response to: turn on the lights"


def test_pipeline_default_echo_handler():
    """Default handler should echo input."""
    pipeline = create_pipeline()

    response = pipeline.process_text("hello")

    assert "hello" in response.lower()


# --- Config Tests ---

def test_pipeline_config_defaults():
    """PipelineConfig should have sensible defaults."""
    config = PipelineConfig()

    assert config.max_recording_duration == 30.0
    assert config.lookback_frames == 10
    assert config.interrupt_enabled


def test_pipeline_uses_custom_config():
    """Pipeline should use provided config."""
    config = PipelineConfig(
        max_recording_duration=10.0,
        lookback_frames=20,
    )

    audio = MockAudioBackend()
    wake = MockWakeWordDetector()
    vad = MockVAD()
    stt = MockSTT()
    tts = MockTTS()

    pipeline = ConversationPipeline(
        audio_backend=audio,
        wake_detector=wake,
        vad_backend=vad,
        stt_engine=stt,
        tts_engine=tts,
        config=config,
    )

    assert pipeline.config.max_recording_duration == 10.0
    assert pipeline.config.lookback_frames == 20


# --- Integration Tests ---

def test_pipeline_full_conversation_flow():
    """Test complete conversation: wake → record → transcribe → respond → speak."""
    events = []

    # Wake word at frame 2, speech at frames 5-15
    pipeline = create_pipeline(
        wake_trigger_frames={2},
        speech_frames=set(range(5, 16)),  # Speech frames 5-15
        stt_response="turn on lights",
        response_handler=lambda x: "Turning on lights",
    )

    pipeline.on_event(lambda e: events.append(e))
    pipeline.start()

    # Wait for full flow
    time.sleep(0.5)

    pipeline.stop()

    # Check event sequence
    event_types = [e.type for e in events]

    # Should have wake word detected
    assert EventType.WAKE_WORD_DETECTED in event_types

    # Should have recording events
    assert EventType.RECORDING_STARTED in event_types


def test_pipeline_multiple_event_handlers():
    """Multiple event handlers should all receive events."""
    handler1_events = []
    handler2_events = []

    pipeline = create_pipeline()

    pipeline.on_event(lambda e: handler1_events.append(e))
    pipeline.on_event(lambda e: handler2_events.append(e))

    pipeline.start()
    pipeline.stop()

    # Both should have received events
    assert len(handler1_events) > 0
    assert len(handler2_events) > 0
    assert len(handler1_events) == len(handler2_events)


def test_pipeline_handler_error_doesnt_crash():
    """Pipeline should continue if event handler raises error."""
    good_events = []

    def bad_handler(e):
        raise ValueError("Intentional error")

    def good_handler(e):
        good_events.append(e)

    pipeline = create_pipeline()

    pipeline.on_event(bad_handler)
    pipeline.on_event(good_handler)

    # Should not raise
    pipeline.start()
    pipeline.stop()

    # Good handler should still have received events
    assert len(good_events) > 0

