"""Tests for VoiceCore state machine and API."""

import pytest

from strawberry.voice import (
    VoiceConfig,
    VoiceController,
    VoiceCore,
    VoiceState,
    VoiceStateChanged,
    VoiceStateError,
    VoiceStatusChanged,
    can_transition,
)


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

        # Cannot go from IDLE to SPEAKING directly
        assert not can_transition(VoiceState.IDLE, VoiceState.SPEAKING)

        # Cannot go from SPEAKING to LISTENING
        assert not can_transition(VoiceState.SPEAKING, VoiceState.LISTENING)

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

        assert config.wake_words == ["strawberry"]
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
