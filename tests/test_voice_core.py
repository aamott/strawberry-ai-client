"""Tests for VoiceCore state machine and API."""

import asyncio
import threading
import time

import numpy as np
import pytest

from strawberry.shared.settings import SettingsManager
from strawberry.voice import (
    VoiceConfig,
    VoiceController,
    VoiceCore,
    VoiceEvent,
    VoiceNoSpeechDetected,
    VoiceState,
    VoiceStateChanged,
    VoiceStateError,
    VoiceStatusChanged,
    can_transition,
)
from strawberry.voice.speaker_fsm import SpeakerState


def make_test_voice_config() -> VoiceConfig:
    """Create a VoiceConfig that uses mock backends for tests.

    Returns:
        VoiceConfig configured for deterministic, dependency-free tests.
    """
    return VoiceConfig(
        stt_backend="mock",
        tts_backend="mock",
        vad_backend="mock",
        wake_backend="mock",
        wake_words=["test_wake_word"],
    )


class TestVoiceState:
    """Tests for VoiceState enum and transitions."""

    def test_initial_state_is_stopped(self):
        """VoiceCore should start in STOPPED state."""
        config = make_test_voice_config()
        core = VoiceCore(config)
        assert core.state == VoiceState.STOPPED
        assert core.get_state() == VoiceState.STOPPED  # Test get_state() method

    def test_valid_transitions(self):
        """Test that valid transitions are allowed."""
        # STOPPED -> IDLE
        assert can_transition(VoiceState.STOPPED, VoiceState.IDLE)

        # IDLE -> LISTENING
        assert can_transition(VoiceState.IDLE, VoiceState.LISTENING)

        # LISTENING -> PROCESSING
        assert can_transition(VoiceState.LISTENING, VoiceState.PROCESSING)

        # PROCESSING -> SPEAKING
        assert can_transition(VoiceState.PROCESSING, VoiceState.SPEAKING)

        # SPEAKING -> IDLE
        assert can_transition(VoiceState.SPEAKING, VoiceState.IDLE)

    def test_invalid_transitions(self):
        """Test that invalid transitions are rejected."""
        # Cannot go from STOPPED to LISTENING directly
        assert not can_transition(VoiceState.STOPPED, VoiceState.LISTENING)

        # CAN go from IDLE to SPEAKING directly (Spontaneous speech)
        assert can_transition(VoiceState.IDLE, VoiceState.SPEAKING)

        # CAN go from SPEAKING to LISTENING (Barge-in)
        assert can_transition(VoiceState.SPEAKING, VoiceState.LISTENING)

    def test_stop_from_any_state(self):
        """Should be able to stop from most states."""
        for state in [VoiceState.IDLE, VoiceState.LISTENING,
                      VoiceState.PROCESSING, VoiceState.SPEAKING]:
            assert can_transition(state, VoiceState.STOPPED)

    def test_error_only_to_stopped(self):
        """ERROR state can only transition to STOPPED."""
        assert can_transition(VoiceState.ERROR, VoiceState.STOPPED)
        assert not can_transition(VoiceState.ERROR, VoiceState.IDLE)


class TestVoiceStateError:
    """Tests for VoiceStateError exception."""

    def test_error_message(self):
        """VoiceStateError should include state names in message."""
        error = VoiceStateError(VoiceState.STOPPED, VoiceState.LISTENING)
        assert "STOPPED" in str(error)
        assert "LISTENING" in str(error)

    def test_error_attributes(self):
        """VoiceStateError should store states as attributes."""
        error = VoiceStateError(VoiceState.IDLE, VoiceState.SPEAKING)
        assert error.current == VoiceState.IDLE
        assert error.attempted == VoiceState.SPEAKING


@pytest.mark.asyncio
class TestVoiceCoreAsync:
    """Async tests for VoiceCore."""

    async def test_start_transitions_to_idle(self):
        """start() should transition state to IDLE."""
        config = make_test_voice_config()
        core = VoiceCore(config)

        # Track events
        events = []
        core.add_listener(lambda e: events.append(e))

        result = await core.start()

        assert result is True
        assert core.state == VoiceState.IDLE
        assert core.is_running() is True

        # Should have emitted status change event
        status_events = [e for e in events if isinstance(e, VoiceStateChanged)]
        assert len(status_events) == 1
        assert status_events[0].new_state == VoiceState.IDLE
        assert status_events[0].old_state == VoiceState.STOPPED

    async def test_stop_transitions_to_stopped(self):
        """stop() should transition state to STOPPED."""
        config = make_test_voice_config()
        core = VoiceCore(config)

        await core.start()
        assert core.state == VoiceState.IDLE

        await core.stop()
        assert core.state == VoiceState.STOPPED
        assert core.is_running() is False

    async def test_session_id_generated_on_start(self):
        """session_id should be generated when started."""
        config = make_test_voice_config()
        core = VoiceCore(config)

        assert core.session_id == ""

        await core.start()
        assert core.session_id.startswith("voice-")

        await core.stop()

    async def test_trigger_wakeword_transitions_to_listening(self):
        """trigger_wakeword() should transition to LISTENING."""
        config = make_test_voice_config()
        core = VoiceCore(config)

        await core.start()
        core.trigger_wakeword()

        assert core.state == VoiceState.LISTENING

        await core.stop()

    async def test_ptt_transitions_to_listening(self):
        """push_to_talk_start should transition to LISTENING."""
        config = make_test_voice_config()
        core = VoiceCore(config)

        await core.start()
        core.push_to_talk_start()

        assert core.state == VoiceState.LISTENING
        assert core.is_push_to_talk_active() is True

        await core.stop()

    async def test_cannot_start_ptt_when_not_idle(self):
        """PTT should not work when not in IDLE state."""
        config = make_test_voice_config()
        core = VoiceCore(config)

        # Not started yet - should not change state
        core.push_to_talk_start()
        assert core.state == VoiceState.STOPPED

    async def test_listener_receives_events(self):
        """Event listeners should receive all events."""
        config = make_test_voice_config()
        core = VoiceCore(config)

        events = []
        core.add_listener(lambda e: events.append(e))

        await core.start()
        await core.stop()

        # Should have received status change events
        assert len(events) >= 2

    async def test_remove_listener(self):
        """Removed listeners should not receive events."""
        config = make_test_voice_config()
        core = VoiceCore(config)

        events = []
        def listener(e):
            return events.append(e)

        core.add_listener(listener)
        core.remove_listener(listener)

        await core.start()
        await core.stop()

        assert len(events) == 0


class TestBackwardsCompatibility:
    """Tests to ensure VoiceController alias works."""

    def test_voicecontroller_is_alias(self):
        """VoiceController should be an alias for VoiceCore."""
        assert VoiceController is VoiceCore

    def test_voicestatuschanged_is_alias(self):
        """VoiceStatusChanged should be an alias for VoiceStateChanged."""
        assert VoiceStatusChanged is VoiceStateChanged


class TestVoiceConfig:
    """Tests for VoiceConfig."""

    def test_default_values(self):
        """VoiceConfig should have sensible defaults."""
        config = VoiceConfig()

        assert config.wake_words == ["hey barista"]
        assert config.sensitivity == 0.5
        assert config.sample_rate == 16000

    def test_custom_values(self):
        """VoiceConfig should accept custom values."""
        config = VoiceConfig(
            wake_words=["hey computer"],
            sensitivity=0.8,
            sample_rate=44100,
        )

        assert config.wake_words == ["hey computer"]
        assert config.sensitivity == 0.8
        assert config.sample_rate == 44100


@pytest.mark.asyncio
class TestVoiceCoreSettingsReload:
    """Tests for VoiceCore runtime settings reload behavior."""

    async def test_tts_fallback_order_updates_without_restart(self, tmp_path):
        """Updating voice_core.tts.order should apply while running.

        This is the regression for the CLI case where the user saves settings
        and expects the new fallback order to be used immediately.
        """
        settings_manager = SettingsManager(config_dir=tmp_path, env_filename=".env")
        core = VoiceCore(
            make_test_voice_config(),
            settings_manager=settings_manager,
        )

        # VoiceCore syncs its backend order from SettingsManager (voice_core.*.order).
        # Override defaults to keep the test dependency-free and deterministic.
        settings_manager.set("voice_core", "stt.order", "mock")
        settings_manager.set("voice_core", "tts.order", "mock")
        settings_manager.set("voice_core", "vad.order", "mock")
        settings_manager.set("voice_core", "wakeword.order", "mock")

        await core.start()

        # Ensure the initial order reflects the settings override.
        assert core.component_manager.tts_backend_names == ["mock"]

        # Change fallback order while running; VoiceCore should pick it up without a restart.
        settings_manager.set("voice_core", "tts.order", "mock,orca")

        # The change callback runs synchronously; backend name list should update immediately.
        # Note: In the new architecture, SettingsHelper updates config, but
        # ComponentManager parses it on reinit/init.
        # SettingsHelper updates VoiceConfig directly. VoiceComponentManager reads it.
        # But ComponentManager parses backend names in `initialize` or `reinitialize_pending`.
        # So we need to ensure reinit happens.
        # The test relies on `settings_manager.set` triggering the callback
        # which triggers `_on_component_settings_changed`.

        # Give the async reinit task a moment to run
        await asyncio.sleep(0.1)

        # Now check if it updated
        assert core.component_manager.tts_backend_names == ["mock", "orca"]

        assert core.component_manager.active_tts_backend == "mock"

        await core.stop()


class TestNoSpeechEvent:
    """Tests for emitting a no-speech event when recording ends silently."""

    def test_finish_recording_emits_no_speech_detected_when_vad_saw_no_speech(self):
        """If VAD never detects speech, VoiceCore should emit a no-speech event."""
        from strawberry.voice.vad.backends.mock import MockVAD
        from strawberry.voice.vad.processor import VADProcessor

        config = make_test_voice_config()
        core = VoiceCore(config)

        events = []
        core.add_listener(lambda e: events.append(e))

        # Start the pipeline first
        core._pipeline.start()

        # Avoid starting the full audio pipeline; we only need VADProcessor state.
        core.component_manager.components.vad_processor = VADProcessor(
            MockVAD(), frame_duration_ms=30
        )

        # Simulate the state reached after wake word / PTT.
        core._pipeline.listener.start_listening()
        core._start_recording()  # Emits VoiceListening and resets VADProcessor  # noqa: SLF001

        # Simulate buffered audio (silence). We intentionally do not call
        # _handle_listening() so VAD never sees speech.
        import numpy as np

        core._recording_buffer.append(np.zeros(480, dtype=np.int16))  # noqa: SLF001

        core._finish_recording()  # Should early-return to IDLE  # noqa: SLF001

        assert core.state == VoiceState.IDLE
        assert any(isinstance(e, VoiceNoSpeechDetected) for e in events)


class TestPTT:
    """Tests for Push-to-Talk logic."""

    def test_ptt_stop_clears_active_flag_early(self):
        """PTT stop should clear active flag even if not listening yet.

        Simulates a quick button press/release where the release happens
        before the system transitions to LISTENING.
        """
        config = make_test_voice_config()
        core = VoiceCore(config)

        # Start PTT (sets active=True)
        # Note: In a real scenario, this might be async or racing with state transitions.
        # We manually set the flag to simulate the race condition where
        # push_to_talk_start was called but we haven't reached LISTENING yet.
        core._pipeline.start()  # Start the pipeline
        core._ptt_active = True

        # Stop PTT
        core.push_to_talk_stop()

        assert core._ptt_active is False

@pytest.mark.asyncio
class TestThreadSafety:
    """Tests for thread safety and event marshaling."""

    async def test_emit_marshals_to_loop(self):
        """_emit called from thread should run listener on loop."""
        config = make_test_voice_config()
        core = VoiceCore(config)
        await core.start()

        loop = asyncio.get_running_loop()
        listener_thread_id = None
        event_received = asyncio.Event()

        def listener(e):
            nonlocal listener_thread_id
            listener_thread_id = threading.get_ident()
            # Signal completion
            if loop.is_running():
                 loop.call_soon_threadsafe(event_received.set)

        core.add_listener(listener)

        # Capture loop thread ID
        loop_thread_id = threading.get_ident()

        # Run emit from a worker thread
        def run_emit():
            core.event_emitter.emit(VoiceEvent())

        t = threading.Thread(target=run_emit)
        t.start()
        t.join()

        # Wait for listener to run
        await asyncio.wait_for(event_received.wait(), timeout=1.0)

        # Verify listener ran on the loop thread
        assert listener_thread_id == loop_thread_id

        await core.stop()

class TestBargeIn:
    """Tests for barge-in functionality."""

    def test_barge_in_stops_speaking(self):
        """Wake word detection during SPEAKING should stop TTS and switch to LISTENING."""
        from strawberry.voice.wakeword.backends.mock import MockWakeWordDetector as MockWakeWord

        config = make_test_voice_config()
        core = VoiceCore(config)

        # Start the pipeline and set up speaking state
        core._pipeline.start()
        core._pipeline.speaker.start_speaking("Test")

        # Setup mock wakeword to return a hit
        mock_wake = MockWakeWord(["test"])
        mock_wake.trigger_on_next()
        core.component_manager.components.wake = mock_wake

        # Simulate audio frame that triggers wake word
        import numpy as np
        core._on_audio_frame(np.zeros(512, dtype=np.int16))

        # Assertions
        assert core.state == VoiceState.LISTENING
        # Speaker should be interrupted
        assert core._pipeline.speaker.state == SpeakerState.INTERRUPTED


class TestInterruptibleSpeech:
    """Tests for interruptible speech (pause/resume)."""

    def test_interruption_buffers_speech(self):
        """Wake word during speaking should move current and pending speech to resume buffer."""
        from strawberry.voice.wakeword.backends.mock import MockWakeWordDetector as MockWakeWord

        config = make_test_voice_config()
        core = VoiceCore(config)

        # Start pipeline and set up speaking state
        core._pipeline.start()
        core._current_speech_text = "Part 1"
        core.speak("Part 2")
        core._pipeline.speaker.start_speaking("Part 1")

        # Interrupt
        mock_wake = MockWakeWord(["test"])
        mock_wake.trigger_on_next()
        core.component_manager.components.wake = mock_wake

        import numpy as np
        core._on_audio_frame(np.zeros(512, dtype=np.int16))

        # Verify
        assert core.state == VoiceState.LISTENING
        assert core._pipeline.speaker.state == SpeakerState.INTERRUPTED
        # Speech should be buffered in speaker FSM
        assert core._pipeline.speaker.has_buffered_speech

    def test_response_defers_during_listening_after_barge_in(self):
        """Responses arriving while LISTENING should be deferred after barge-in."""
        from strawberry.voice.wakeword.backends.mock import MockWakeWordDetector as MockWakeWord

        config = make_test_voice_config()
        core = VoiceCore(config)

        # Start pipeline and set up speaking state
        core._pipeline.start()
        core._pipeline.speaker.start_speaking("Test")

        # Trigger wake word to barge in
        mock_wake = MockWakeWord(["test"])
        mock_wake.trigger_on_next()
        core.component_manager.components.wake = mock_wake

        import numpy as np
        core._on_audio_frame(np.zeros(512, dtype=np.int16))

        assert core.state == VoiceState.LISTENING
        assert core._pipeline.speaker.state == SpeakerState.INTERRUPTED

        # Simulate speak loop delivering a response while LISTENING
        core._speak_response("Deferred response")

        assert core.state == VoiceState.LISTENING
        # Response should be buffered in speaker FSM
        assert "Deferred response" in core._pipeline.speaker._buffer

    def test_no_speech_resumes_buffer(self):
        """No speech detected after interruption should resume from buffer."""
        config = make_test_voice_config()
        core = VoiceCore(config)

        # Start pipeline and set up listening state with buffered speech
        core._pipeline.start()
        core._pipeline.listener.start_listening()
        core._pipeline.speaker._buffer = ["Saved 1", "Saved 2"]
        core._recording_start_time = time.time()

        # Setup mock VAD that saw NO speech
        from strawberry.voice.vad.backends.mock import MockVAD
        from strawberry.voice.vad.processor import VADProcessor
        core.component_manager.components.vad_processor = VADProcessor(MockVAD())

        # Finish recording (silent)
        core._finish_recording()

        # Verify - buffer should be cleared and items in speak queue
        assert core._pipeline.speaker._buffer == []
        assert core._speak_queue.get_nowait() == "Saved 1"
        assert core._speak_queue.get_nowait() == "Saved 2"

    def test_new_speech_clears_buffer(self):
        """New valid speech should clear the resume buffer."""
        config = make_test_voice_config()
        core = VoiceCore(config)

        # Start pipeline and set up processing state with buffered speech
        core._pipeline.start()
        core._pipeline.listener.start_listening()
        core._pipeline.listener.start_processing()
        core._pipeline.speaker._buffer = ["Old 1"]

        # Setup mock STT result
        from strawberry.voice.stt.base import TranscriptionResult

        def mock_stt_success(audio):
            return TranscriptionResult(text="New Command")

        # We need to mock the stt component
        class MockSTT:
            def transcribe(self, audio): return TranscriptionResult(text="New Command")

        core.component_manager.components.stt = MockSTT()
        core.component_manager.stt_backend_names = ["mock"]
        core.component_manager.active_stt_backend = "mock"

        # Run process sync
        core._process_audio_sync(np.zeros(1600, dtype=np.int16))

        # Verify - buffer should be cleared
        assert core._pipeline.speaker._buffer == []
        # Check if it tried to speak the new command (it would be in the queue)
        # However, _process_audio_sync calls self.speak(response) if handler exists.
        # If no handler, it just goes IDLE.

class TestStateMachineFixes:
    """Tests for recent state machine fixes."""

    def test_spontaneous_speech_from_idle(self):
        """Should be able to speak directly from IDLE state."""
        config = make_test_voice_config()
        core = VoiceCore(config)

        # Start the pipeline so state is IDLE
        core._pipeline.start()

        # This used to fail with Invalid state transition IDLE -> SPEAKING
        # Now it should work because we allowed it in state.py
        core._speak_response("Hello")
        # After speaking completes, should be back to IDLE
        assert core.state == VoiceState.IDLE

    def test_false_alarm_interruption_cycle(self):
        """Full cycle: Speaking -> Interrupted -> False Alarm -> Resuming -> Speaking."""
        from strawberry.voice.vad.backends.mock import MockVAD
        from strawberry.voice.vad.processor import VADProcessor
        from strawberry.voice.wakeword.backends.mock import MockWakeWordDetector as MockWakeWord

        config = make_test_voice_config()
        core = VoiceCore(config)

        # Start pipeline and set up speaking state
        core._pipeline.start()
        core._current_speech_text = "Original"
        core._pipeline.speaker.start_speaking("Original")

        # 2. Interruption (Wake Word)
        mock_wake = MockWakeWord(["test"])
        mock_wake.trigger_on_next()
        core.component_manager.components.wake = mock_wake

        import numpy as np
        core._on_audio_frame(np.zeros(512, dtype=np.int16))

        assert core.state == VoiceState.LISTENING
        assert core._pipeline.speaker.has_buffered_speech

        # 3. False Alarm (No Speech)
        core.component_manager.components.vad_processor = VADProcessor(MockVAD())
        core._recording_start_time = time.time()

        core._finish_recording()

        # 4. Should be IDLE and items in queue
        assert core.state == VoiceState.IDLE
        assert core._speak_queue.get_nowait() == "Original"

        # 5. Background loop would now call _speak_response("Original")
        # which transitions IDLE -> SPEAKING. This must be valid.
        core._speak_response("Original")
        assert core.state == VoiceState.IDLE
