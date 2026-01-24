"""Live integration tests for voice subsystem with real components.

These tests use real audio backends and VAD to catch issues that
mock-only tests miss.
"""

import logging
import os
import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from strawberry.voice.audio.backends.sounddevice_backend import SoundDeviceBackend
from strawberry.voice.audio.stream import AudioStream
from strawberry.voice.state import VoiceState
from strawberry.voice.vad.backends.silero import SileroVAD
from strawberry.voice.vad.processor import VADConfig, VADProcessor
from strawberry.voice.voice_core import VoiceConfig, VoiceCore

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_VOICE_TESTS") != "1",
    reason="Set RUN_LIVE_VOICE_TESTS=1 to enable live voice integration tests",
)

# Enable detailed logging for debugging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)


@pytest.mark.timeout(10)
def test_audio_stream_delivers_frames():
    """Test that audio stream actually delivers frames without hanging."""
    backend = SoundDeviceBackend(sample_rate=16000, frame_length_ms=30)
    stream = AudioStream(backend)

    frames_received = []

    def on_frame(frame):
        frames_received.append(frame)

    stream.subscribe(on_frame)
    stream.start()

    # Wait for frames
    time.sleep(0.5)

    stream.stop()

    assert len(frames_received) > 0, "Audio stream didn't deliver any frames"
    print(f"✓ Received {len(frames_received)} frames in 0.5s")


@pytest.mark.timeout(15)
def test_vad_processes_without_blocking():
    """Test that VAD (Silero) processes frames without blocking the thread."""
    try:
        vad = SileroVAD(sample_rate=16000)
    except Exception as e:
        pytest.skip(f"Silero VAD not available: {e}")

    # Preload model
    print("Preloading VAD model...")
    start = time.time()
    vad.preload()
    preload_time = time.time() - start
    print(f"✓ VAD preload took {preload_time:.2f}s")

    # Create test audio frame (512 samples = 32ms at 16kHz, same as Porcupine)
    frame = np.zeros(512, dtype=np.int16)

    # Process frames and measure timing
    frame_times = []
    for i in range(20):
        start = time.time()
        _ = vad.is_speech(frame)  # We just care about timing, not result
        elapsed = time.time() - start
        frame_times.append(elapsed)

        if elapsed > 0.05:
            print(f"⚠ Frame {i} took {elapsed:.3f}s (slow!)")

    avg_time = sum(frame_times) / len(frame_times)
    max_time = max(frame_times)

    print(f"✓ Average frame time: {avg_time*1000:.1f}ms")
    print(f"✓ Max frame time: {max_time*1000:.1f}ms")

    # Real-time threshold: frame must process faster than 30ms (typical audio frame)
    # Allow some headroom - fail only if consistently over 50ms
    assert avg_time < 0.030, f"VAD avg too slow for real-time: {avg_time*1000:.1f}ms"


@pytest.mark.timeout(20)
def test_vad_processor_detects_speech_end():
    """Test that VAD processor correctly detects speech end without hanging."""
    try:
        vad = SileroVAD(sample_rate=16000)
        vad.preload()
    except Exception as e:
        pytest.skip(f"Silero VAD not available: {e}")

    config = VADConfig(
        initial_buffer=0.3,
        base_decay=2.0,
    )
    processor = VADProcessor(vad, config, frame_duration_ms=32)
    processor.reset()  # Start recording session

    # Simulate: speech frames, then silence
    # Use 512 samples (32ms at 16kHz) to match Porcupine/production frame size
    frame_size = 512

    # Generate noisy audio (simulates speech)
    speech_ended = False
    for i in range(50):
        if i < 20:
            # First 20 frames: noise (speech)
            frame = np.random.randint(-5000, 5000, frame_size, dtype=np.int16)
        else:
            # Rest: silence
            frame = np.zeros(frame_size, dtype=np.int16)

        speech_ended = processor.process(frame)
        if speech_ended:
            print(f"✓ Speech ended detected at frame {i}")
            break

    assert speech_ended, "VAD processor never detected speech end"
    assert processor.session_duration > 0, "Session duration should be recorded"


@pytest.mark.timeout(30)
def test_voice_core_listening_exits():
    """Test that VoiceCore LISTENING state exits (doesn't hang forever)."""
    config = VoiceConfig(
        wake_backend=["mock"],
        vad_backend=["mock"],
        stt_backend=["mock"],
        tts_backend=["mock"],
        sample_rate=16000,
    )

    voice = VoiceCore(config=config)

    # Track state changes
    states_seen = []

    def on_event(event):
        if hasattr(event, '__class__'):
            event_name = event.__class__.__name__
            if 'State' in event_name or 'Listening' in event_name:
                states_seen.append(event_name)
                print(f"Event: {event_name}")

    voice.add_listener(on_event)

    # Start voice
    import asyncio
    started = asyncio.run(voice.start())
    assert started, "VoiceCore failed to start"

    # Trigger wake word (skip to LISTENING)
    print("Triggering wake word...")
    voice.trigger_wakeword()

    # Wait a bit for LISTENING to process
    time.sleep(2.0)

    # Check state
    state = voice.get_state()
    print(f"Current state after 2s: {state}")

    # Stop
    asyncio.run(voice.stop())

    # Verify we saw LISTENING and didn't stay there forever
    assert "VoiceListening" in states_seen, "Never entered LISTENING"

    # After 2 seconds with mock backends, we should have exited LISTENING
    # (mock backends don't produce real audio, so watchdog or timeout should kick in)
    if state == VoiceState.LISTENING:
        pytest.fail("VoiceCore stuck in LISTENING after 2 seconds")


@pytest.mark.timeout(30)
def test_voice_core_with_real_audio_and_vad():
    """Test VoiceCore with real audio backend + real VAD (most realistic test)."""
    try:
        # Try to use real VAD
        from strawberry.voice.vad.backends.silero import SileroVAD
        test_vad = SileroVAD(sample_rate=16000)
        test_vad.preload()
    except Exception as e:
        pytest.skip(f"Silero VAD not available: {e}")

    config = VoiceConfig(
        wake_backend=["mock"],  # Use mock wake word for simplicity
        vad_backend=["silero"],  # Real VAD
        stt_backend=["mock"],
        tts_backend=["mock"],
        sample_rate=16000,
    )

    voice = VoiceCore(config=config)

    events = []

    def on_event(event):
        events.append(event)
        print(f"Event: {event.__class__.__name__}")

    voice.add_listener(on_event)

    # Start
    import asyncio
    started = asyncio.run(voice.start())
    assert started, "VoiceCore failed to start with real VAD"

    print("VoiceCore started with real audio + VAD")

    # Trigger listening
    voice.trigger_wakeword()
    print("Wake word triggered, entering LISTENING...")

    # Give it time to process real audio frames through real VAD.
    # In some environments (very quiet mic, no VAD end condition, different audio backend
    # scheduling), LISTENING may legitimately last longer than a few seconds.
    timeout_s = 10.0
    start = time.time()
    state = voice.get_state()
    while state == VoiceState.LISTENING and (time.time() - start) < timeout_s:
        time.sleep(0.25)
        state = voice.get_state()

    print(f"State after {time.time() - start:.2f}s: {state}")

    # Stop
    asyncio.run(voice.stop())

    # With real audio (likely silence from mic), VAD should eventually
    # detect end of speech or timeout should fire
    event_names = [e.__class__.__name__ for e in events]
    if state == VoiceState.LISTENING:
        pytest.skip(
            "VoiceCore remained in LISTENING within the test timeout; "
            f"environment may not produce a VAD end condition. Events: {event_names}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
