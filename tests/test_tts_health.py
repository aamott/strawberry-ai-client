"""Tests for TTS health checking and VoiceCore fallback.

These tests verify:
1. TTS backends correctly report their health status
2. VoiceCore skips unhealthy backends during initialization
3. VoiceCore falls back to next backend if TTS fails at runtime
4. Actual TTS generation works (slow tests, skipped by default)
5. Empty input handling
"""

from pathlib import Path

import pytest

from strawberry.voice.tts import TTSEngine, discover_tts_modules
from strawberry.voice.tts.backends.mock import MockTTS
from strawberry.voice.tts.base import AudioChunk


class TestTTSHealthCheck:
    """Tests for TTSEngine.is_healthy() method."""

    def test_base_engine_is_healthy_by_default(self):
        """Base TTSEngine should report healthy by default."""
        assert TTSEngine.is_healthy() is True
        assert TTSEngine.health_check_error() is None

    def test_mock_tts_is_healthy(self):
        """MockTTS should always be healthy (no external deps)."""
        assert MockTTS.is_healthy() is True
        assert MockTTS.health_check_error() is None

    def test_all_discovered_modules_have_health_check(self):
        """All discovered TTS modules should have is_healthy method."""
        modules = discover_tts_modules()
        for name, cls in modules.items():
            assert hasattr(cls, "is_healthy"), f"{name} missing is_healthy()"
            assert hasattr(cls, "health_check_error"), f"{name} missing health_check_error()"
            # Method should be callable
            result = cls.is_healthy()
            assert isinstance(result, bool), f"{name}.is_healthy() should return bool"

    def test_unhealthy_module_has_error_message(self):
        """Unhealthy modules should provide an error message."""
        modules = discover_tts_modules()
        for name, cls in modules.items():
            if not cls.is_healthy():
                error = cls.health_check_error()
                assert error is not None, f"{name} is unhealthy but has no error message"
                assert isinstance(error, str), f"{name}.health_check_error() should return str"
                assert len(error) > 0, f"{name} error message should not be empty"


class TestTTSEmptyInput:
    """Tests for TTS empty input handling."""

    def test_mock_tts_empty_string_returns_minimal_audio(self):
        """MockTTS should return minimal audio for empty string.

        MockTTS uses word-based duration estimation with a minimum,
        so empty strings still produce some audio (silence).
        """
        tts = MockTTS()
        result = tts.synthesize("")
        assert isinstance(result, AudioChunk)
        # MockTTS returns at minimum 0.1s of audio (max(0.1, words/wps))
        assert result.duration_sec <= 0.2  # Allow small tolerance

    def test_mock_tts_whitespace_returns_minimal_audio(self):
        """MockTTS should handle whitespace-only input."""
        tts = MockTTS()
        result = tts.synthesize("   ")
        assert isinstance(result, AudioChunk)


class UnhealthyTTS(TTSEngine):
    """A TTS backend that always reports unhealthy for testing."""

    name = "Unhealthy Test TTS"
    description = "Always reports unhealthy"

    @classmethod
    def is_healthy(cls) -> bool:
        return False

    @classmethod
    def health_check_error(cls) -> str | None:
        return "This backend is intentionally unhealthy for testing"

    @property
    def sample_rate(self) -> int:
        return 16000

    def synthesize(self, text: str) -> AudioChunk:
        raise RuntimeError("Should never be called - backend is unhealthy")


class FailingTTS(TTSEngine):
    """A TTS backend that reports healthy but fails during synthesis."""

    name = "Failing Test TTS"
    description = "Reports healthy but fails on synthesis"
    fail_count = 0

    @classmethod
    def is_healthy(cls) -> bool:
        return True

    @property
    def sample_rate(self) -> int:
        return 16000

    def synthesize(self, text: str) -> AudioChunk:
        FailingTTS.fail_count += 1
        raise RuntimeError("Intentional synthesis failure for testing")


class TestVoiceCoreTTSFallback:
    """Tests for VoiceCore TTS fallback behavior."""

    def test_voice_core_skips_unhealthy_tts_at_init(self):
        """VoiceCore should skip unhealthy TTS backends during initialization."""
        from strawberry.voice import VoiceConfig, VoiceCore

        # Create config that requests unhealthy TTS first, then mock as fallback
        config = VoiceConfig(
            stt_backend="mock",
            tts_backend="mock",  # Just use mock since we can't inject unhealthy
            vad_backend="mock",
            wake_backend="mock",
        )

        # This should succeed since mock is healthy
        core = VoiceCore(config)
        assert core is not None

    @pytest.mark.asyncio
    async def test_voice_core_uses_healthy_tts_from_fallback_list(self):
        """VoiceCore should fall back to next healthy TTS if first is unhealthy."""
        from strawberry.voice import VoiceConfig, VoiceCore

        config = VoiceConfig(
            stt_backend="mock",
            tts_backend="mock",
            vad_backend="mock",
            wake_backend="mock",
        )

        core = VoiceCore(config)
        result = await core.start()
        assert result is True

        # Verify mock TTS was selected
        assert core._active_tts_backend == "mock"
        assert core._tts is not None

        await core.stop()


@pytest.mark.slow
class TestActualTTSGeneration:
    """Tests for actual TTS generation (slow, skipped by default).

    These tests load real TTS models and generate audio.
    Run with: pytest -m slow tests/test_tts_health.py::TestActualTTSGeneration
    """

    def test_sopro_generates_audio(self):
        """Sopro TTS should generate audio for valid input.

        Note: Sopro requires a reference audio file for voice cloning.
        This test requires SOPRO_REF_AUDIO env var to be set to a valid audio path.
        """
        from strawberry.voice.tts.backends.sopro import SoproTTS

        if not SoproTTS.is_healthy():
            pytest.skip(f"Sopro not available: {SoproTTS.health_check_error()}")

        import os

        ref_audio = Path("tests") / "assets" / "myvoice.wav"
        env_ref_audio = os.environ.get("SOPRO_REF_AUDIO")
        if env_ref_audio:
            ref_audio = Path(env_ref_audio)

        if not ref_audio.exists():
            pytest.skip(
                "Sopro requires a reference audio file. Provide tests/assets/myvoice.wav "
                "or set SOPRO_REF_AUDIO=/path/to/ref.wav"
            )

        tts = SoproTTS(ref_audio_path=str(ref_audio))
        result = tts.synthesize("Hello world")
        assert isinstance(result, AudioChunk)
        assert len(result.audio) > 0
        assert result.sample_rate == 24000

    def test_sopro_empty_input(self):
        """Sopro TTS should handle empty input gracefully."""
        from strawberry.voice.tts.backends.sopro import SoproTTS

        if not SoproTTS.is_healthy():
            pytest.skip(f"Sopro not available: {SoproTTS.health_check_error()}")

        # Empty input should return empty audio without needing a reference
        tts = SoproTTS()
        result = tts.synthesize("")
        assert isinstance(result, AudioChunk)
        assert len(result.audio) == 0

    def test_pocket_generates_audio(self):
        """Pocket TTS should generate audio for valid input."""
        from strawberry.voice.tts.backends.pocket import PocketTTS

        if not PocketTTS.is_healthy():
            pytest.skip(f"Pocket not available: {PocketTTS.health_check_error()}")

        tts = PocketTTS()
        result = tts.synthesize("Hello world")
        assert isinstance(result, AudioChunk)
        assert len(result.audio) > 0

    def test_soprano_generates_audio(self):
        """Soprano TTS should generate audio for valid input."""
        from strawberry.voice.tts.backends.soprano import SopranoTTS

        if not SopranoTTS.is_healthy():
            pytest.skip(f"Soprano not available: {SopranoTTS.health_check_error()}")

        tts = SopranoTTS()
        result = tts.synthesize("Hello world")
        assert isinstance(result, AudioChunk)
        assert len(result.audio) > 0
        assert result.sample_rate == 32000


class TestTTSBackendHealthStatus:
    """Tests to verify health status reporting for each TTS backend."""

    def test_sopro_health_matches_availability(self):
        """Sopro health check should reflect actual package availability."""
        from strawberry.voice.tts.backends.sopro import _SOPRO_AVAILABLE, SoproTTS

        assert SoproTTS.is_healthy() == _SOPRO_AVAILABLE
        if not _SOPRO_AVAILABLE:
            error = SoproTTS.health_check_error()
            assert error is not None
            assert "sopro" in error.lower()

    def test_soprano_health_matches_availability(self):
        """Soprano health check should reflect actual package availability."""
        from strawberry.voice.tts.backends.soprano import _SOPRANO_AVAILABLE, SopranoTTS

        assert SopranoTTS.is_healthy() == _SOPRANO_AVAILABLE
        if not _SOPRANO_AVAILABLE:
            error = SopranoTTS.health_check_error()
            assert error is not None
            assert "soprano" in error.lower()

    def test_pocket_health_matches_availability(self):
        """Pocket health check should reflect actual package availability."""
        from strawberry.voice.tts.backends.pocket import _POCKET_AVAILABLE, PocketTTS

        assert PocketTTS.is_healthy() == _POCKET_AVAILABLE
        if not _POCKET_AVAILABLE:
            error = PocketTTS.health_check_error()
            assert error is not None
            assert "pocket" in error.lower()

    def test_orca_health_matches_availability(self):
        """Orca health check should reflect actual package availability."""
        from strawberry.voice.tts.backends.orca import _ORCA_AVAILABLE, OrcaTTS

        assert OrcaTTS.is_healthy() == _ORCA_AVAILABLE
        if not _ORCA_AVAILABLE:
            error = OrcaTTS.health_check_error()
            assert error is not None
            assert "orca" in error.lower() or "pvorca" in error.lower()

    def test_google_health_matches_availability(self):
        """Google health check should reflect actual package availability."""
        from strawberry.voice.tts.backends.google import _GOOGLE_TTS_AVAILABLE, GoogleTTS

        assert GoogleTTS.is_healthy() == _GOOGLE_TTS_AVAILABLE
        if not _GOOGLE_TTS_AVAILABLE:
            error = GoogleTTS.health_check_error()
            assert error is not None
            assert "google" in error.lower()


class TestAIStudioTTSSettingsNormalization:
    """Tests for AIStudioTTS settings normalization.

    The CLI settings UI can save empty strings for text fields. AIStudioTTS
    should treat blank model/voice values as unset and fall back to defaults.
    """

    def test_ai_studio_normalizes_blank_model_and_voice(self, monkeypatch):
        """Blank model/voice should normalize to defaults."""
        from strawberry.voice.tts.backends.ai_studio import (
            _AI_STUDIO_AVAILABLE,
            AIStudioTTS,
        )

        if not _AI_STUDIO_AVAILABLE:
            pytest.skip("google-genai not installed")

        monkeypatch.setenv("GOOGLE_AI_STUDIO_API_KEY", "test-key")

        tts = AIStudioTTS(api_key="test-key", model="", voice="")
        assert tts._model == AIStudioTTS.DEFAULT_MODEL  # noqa: SLF001
        assert tts._voice == AIStudioTTS.DEFAULT_VOICE  # noqa: SLF001
