"""Tests for audio feedback module."""

import numpy as np

from strawberry.audio.feedback import (
    SOUND_CONFIGS,
    AudioFeedback,
    FeedbackSound,
    ToneConfig,
    get_feedback,
)


class TestToneGeneration:
    """Tests for tone generation."""

    def test_generates_correct_duration(self):
        """Test that generated tones have correct duration."""
        feedback = AudioFeedback(sample_rate=44100, enabled=True)

        config = ToneConfig(
            frequencies=[440],
            duration=0.5,
            volume=0.3,
        )

        audio = feedback._generate_tone(config)

        expected_samples = int(44100 * 0.5)
        assert len(audio) == expected_samples

    def test_generates_float32_array(self):
        """Test that output is float32."""
        feedback = AudioFeedback(sample_rate=44100, enabled=True)

        config = ToneConfig(
            frequencies=[440],
            duration=0.1,
            volume=0.3,
        )

        audio = feedback._generate_tone(config)
        assert audio.dtype == np.float32

    def test_volume_is_applied(self):
        """Test that volume setting affects output."""
        feedback = AudioFeedback(sample_rate=44100, enabled=True)

        loud_config = ToneConfig(frequencies=[440], duration=0.1, volume=1.0)
        quiet_config = ToneConfig(frequencies=[440], duration=0.1, volume=0.1)

        loud = feedback._generate_tone(loud_config)
        quiet = feedback._generate_tone(quiet_config)

        assert np.max(np.abs(loud)) > np.max(np.abs(quiet))

    def test_all_sounds_are_pregenerated(self):
        """Test that all sound types are pre-generated."""
        feedback = AudioFeedback(sample_rate=44100, enabled=True)

        for sound in FeedbackSound:
            assert sound in feedback._sounds
            assert len(feedback._sounds[sound]) > 0


class TestAudioFeedback:
    """Tests for AudioFeedback class."""

    def test_enabled_by_default(self):
        """Test feedback is enabled by default when created with enabled=True."""
        feedback = AudioFeedback(enabled=True)
        assert feedback.enabled is True

    def test_can_disable(self):
        """Test feedback can be disabled."""
        feedback = AudioFeedback(enabled=True)
        feedback.set_enabled(False)
        assert feedback.enabled is False

    def test_get_feedback_returns_same_instance(self):
        """Test global instance is reused."""
        feedback1 = get_feedback(enabled=True)
        feedback2 = get_feedback(enabled=True)
        assert feedback1 is feedback2

    def test_play_when_disabled_does_nothing(self):
        """Test that play() does nothing when disabled."""
        feedback = AudioFeedback(enabled=False)
        # Should not raise any exception
        feedback.play(FeedbackSound.WAKE_DETECTED)


class TestSoundConfigs:
    """Tests for sound configuration definitions."""

    def test_all_sounds_have_configs(self):
        """Test all FeedbackSound types have configurations."""
        for sound in FeedbackSound:
            assert sound in SOUND_CONFIGS

    def test_configs_have_required_fields(self):
        """Test all configs have required fields."""
        for sound, config in SOUND_CONFIGS.items():
            assert len(config.frequencies) > 0
            assert config.duration > 0
            assert 0 <= config.volume <= 1

    def test_wake_detected_is_pleasant(self):
        """Test wake detected sound is an A major chord (pleasant)."""
        config = SOUND_CONFIGS[FeedbackSound.WAKE_DETECTED]
        # A major: A4 (440), C#5 (554.37), E5 (659.26)
        assert 440 in config.frequencies or any(abs(f - 440) < 5 for f in config.frequencies)

    def test_error_sound_is_lower(self):
        """Test error sound uses lower frequencies."""
        wake_config = SOUND_CONFIGS[FeedbackSound.WAKE_DETECTED]
        error_config = SOUND_CONFIGS[FeedbackSound.ERROR]

        wake_avg = sum(wake_config.frequencies) / len(wake_config.frequencies)
        error_avg = sum(error_config.frequencies) / len(error_config.frequencies)

        assert error_avg < wake_avg  # Error should sound lower


class TestConvenienceMethods:
    """Tests for convenience methods."""

    def test_convenience_methods_exist(self):
        """Test all convenience methods exist."""
        feedback = AudioFeedback(enabled=False)

        # These should not raise AttributeError
        feedback.play_wake_detected
        feedback.play_recording_start
        feedback.play_recording_end
        feedback.play_processing
        feedback.play_success
        feedback.play_error
        feedback.play_ready

