"""Tests for STT fallback behaviour.

Covers:
- component_manager.init_stt_backend returns bool and tracks errors
- voice_core._try_stt_backends falls back through backends on errors
- Clear user-facing error summaries with auth / dependency hints
"""

from typing import List
from unittest.mock import MagicMock

import numpy as np

from strawberry.voice.component_manager import VoiceComponentManager
from strawberry.voice.config import VoiceConfig
from strawberry.voice.events import VoiceError
from strawberry.voice.stt.base import STTEngine, TranscriptionResult
from strawberry.voice.voice_core import VoiceCore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**overrides) -> VoiceConfig:
    """Create a VoiceConfig for tests using mock backends."""
    defaults = dict(
        stt_backend="mock",
        tts_backend="mock",
        vad_backend="mock",
        wake_backend="mock",
        wake_words=["test"],
    )
    defaults.update(overrides)
    return VoiceConfig(**defaults)


class _FailingSTT(STTEngine):
    """STT engine that crashes on transcribe."""

    name = "FailingSTT"

    def __init__(self, error_msg: str = "boom", **kwargs):
        self._error_msg = error_msg

    @property
    def sample_rate(self) -> int:
        return 16000

    def transcribe(self, audio: np.ndarray) -> TranscriptionResult:
        raise RuntimeError(self._error_msg)


class _GoodSTT(STTEngine):
    """STT engine that always succeeds."""

    name = "GoodSTT"

    @property
    def sample_rate(self) -> int:
        return 16000

    def transcribe(self, audio: np.ndarray) -> TranscriptionResult:
        return TranscriptionResult(text="hello world")


# ---------------------------------------------------------------------------
# ComponentManager — init_stt_backend
# ---------------------------------------------------------------------------

class TestInitSttBackend:
    """Tests for VoiceComponentManager.init_stt_backend."""

    def _make_manager(self) -> VoiceComponentManager:
        config = _make_config()
        mgr = VoiceComponentManager(config)
        # Inject discovered modules (skip real discovery)
        mgr._stt_modules = {"good": _GoodSTT, "failing": _FailingSTT}
        return mgr

    def test_returns_false_for_unknown_backend(self):
        """Missing backend name should return False and record error."""
        mgr = self._make_manager()
        assert mgr.init_stt_backend("nonexistent") is False
        assert "nonexistent" in mgr._stt_init_errors
        assert "not found" in mgr._stt_init_errors["nonexistent"]

    def test_returns_false_on_init_exception(self):
        """If the backend constructor throws, should return False."""
        mgr = self._make_manager()

        # Patch _FailingSTT to crash in __init__
        class _CrashOnInit(STTEngine):
            name = "CrashOnInit"

            def __init__(self, **kwargs):
                raise ValueError("bad config value")

            @property
            def sample_rate(self) -> int:
                return 16000

            def transcribe(self, audio):
                pass

        mgr._stt_modules["crash"] = _CrashOnInit
        assert mgr.init_stt_backend("crash") is False
        assert "crash" in mgr._stt_init_errors
        assert "bad config value" in mgr._stt_init_errors["crash"]

    def test_returns_true_on_success(self):
        """Successful init should return True and set active backend."""
        mgr = self._make_manager()
        assert mgr.init_stt_backend("good") is True
        assert mgr.active_stt_backend == "good"
        assert isinstance(mgr.components.stt, _GoodSTT)

    def test_cleans_up_previous_backend(self):
        """Switching backends should call cleanup on the old one."""
        mgr = self._make_manager()
        mgr.init_stt_backend("good")
        old_stt = mgr.components.stt
        old_stt.cleanup = MagicMock()

        mgr.init_stt_backend("good")  # re-init same backend
        old_stt.cleanup.assert_called_once()


# ---------------------------------------------------------------------------
# VoiceCore — _try_stt_backends
# ---------------------------------------------------------------------------

class TestTrySttBackends:
    """Tests for VoiceCore._try_stt_backends fallback loop."""

    def _make_core(self, stt_backend: str = "mock") -> VoiceCore:
        config = _make_config(stt_backend=stt_backend)
        core = VoiceCore(config)
        # Do NOT set an event loop — this makes emit() call listeners
        # directly (synchronously) instead of marshaling via
        # call_soon_threadsafe, which is what we want in tests.
        return core

    def _collected_errors(self, core: VoiceCore) -> List[VoiceError]:
        """Collect VoiceError events from the emitter."""
        errors: List[VoiceError] = []
        core.event_emitter.add_listener(
            lambda e: errors.append(e) if isinstance(e, VoiceError) else None
        )
        return errors

    def test_fallback_to_second_backend(self):
        """When first backend fails transcription, should try the next."""
        core = self._make_core(stt_backend="failing,good")
        mgr = core.component_manager
        mgr._stt_modules = {"failing": _FailingSTT, "good": _GoodSTT}
        mgr.stt_backend_names = ["failing", "good"]

        # Start with failing backend
        mgr.init_stt_backend("failing")

        audio = np.zeros(1600, dtype=np.int16)
        result = core._try_stt_backends(audio)

        assert result is not None
        assert result.text == "hello world"
        # Should have switched to 'good'
        assert mgr.active_stt_backend == "good"

    def test_fallback_on_init_failure(self):
        """When first backend fails to init, should try the next."""
        core = self._make_core(stt_backend="nonexistent,good")
        mgr = core.component_manager
        mgr._stt_modules = {"good": _GoodSTT}
        mgr.stt_backend_names = ["nonexistent", "good"]

        # Ensure no active stt to force init
        mgr.components.stt = None
        mgr.active_stt_backend = None

        audio = np.zeros(1600, dtype=np.int16)
        result = core._try_stt_backends(audio)

        assert result is not None
        assert result.text == "hello world"

    def test_all_fail_emits_summary_error(self):
        """When all backends fail, should emit a single summary VoiceError."""
        core = self._make_core(stt_backend="failing")
        mgr = core.component_manager
        mgr._stt_modules = {"failing": _FailingSTT}
        mgr.stt_backend_names = ["failing"]
        mgr.init_stt_backend("failing")

        errors = self._collected_errors(core)
        audio = np.zeros(1600, dtype=np.int16)
        result = core._try_stt_backends(audio)

        assert result is None
        assert len(errors) == 1
        assert "All STT backends failed" in errors[0].error
        assert "failing" in errors[0].error

    def test_auth_hint_included(self):
        """When errors look like auth failures, hint is included."""
        # Create a backend that fails with an auth-like message
        class _AuthFailSTT(_FailingSTT):
            def __init__(self, **kwargs):
                super().__init__(error_msg="401 Unauthorized", **kwargs)

        core = self._make_core(stt_backend="authfail")
        mgr = core.component_manager
        mgr._stt_modules = {"authfail": _AuthFailSTT}
        mgr.stt_backend_names = ["authfail"]
        mgr.init_stt_backend("authfail")

        errors = self._collected_errors(core)
        core._try_stt_backends(np.zeros(1600, dtype=np.int16))

        assert len(errors) == 1
        assert "API key" in errors[0].error or "credentials" in errors[0].error

    def test_dep_hint_included(self):
        """When errors look like missing packages, hint is included."""

        class _DepFailSTT(_FailingSTT):
            def __init__(self, **kwargs):
                super().__init__(
                    error_msg="No module named 'pvleopard'", **kwargs
                )

        core = self._make_core(stt_backend="depfail")
        mgr = core.component_manager
        mgr._stt_modules = {"depfail": _DepFailSTT}
        mgr.stt_backend_names = ["depfail"]
        mgr.init_stt_backend("depfail")

        errors = self._collected_errors(core)
        core._try_stt_backends(np.zeros(1600, dtype=np.int16))

        assert len(errors) == 1
        assert "pip install" in errors[0].error


# ---------------------------------------------------------------------------
# VoiceCore — _looks_like_missing_dep
# ---------------------------------------------------------------------------

class TestMissingDepDetection:
    """Tests for _looks_like_missing_dep helper."""

    def test_detects_no_module_named(self):
        core = VoiceCore(_make_config())
        assert core._looks_like_missing_dep("No module named 'pvleopard'")

    def test_detects_import_error(self):
        core = VoiceCore(_make_config())
        assert core._looks_like_missing_dep("ImportError: cannot import name 'X'")

    def test_detects_not_installed(self):
        core = VoiceCore(_make_config())
        assert core._looks_like_missing_dep(
            "google-cloud-speech not installed"
        )

    def test_ignores_unrelated(self):
        core = VoiceCore(_make_config())
        assert not core._looks_like_missing_dep("timeout after 30s")


# ---------------------------------------------------------------------------
# VoiceCore — failure caching
# ---------------------------------------------------------------------------

class TestFailureCaching:
    """Tests for caching permanently failed backends."""

    def _make_core(self, stt_backend: str = "mock") -> VoiceCore:
        config = _make_config(stt_backend=stt_backend)
        return VoiceCore(config)

    def test_failed_backend_not_retried(self):
        """A backend that failed once should be skipped on subsequent calls."""
        call_count = 0

        class _CountingFailSTT(_FailingSTT):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)

            def transcribe(self, audio):
                nonlocal call_count
                call_count += 1
                raise RuntimeError("always fails")

        core = self._make_core(stt_backend="counting")
        mgr = core.component_manager
        mgr._stt_modules = {"counting": _CountingFailSTT}
        mgr.stt_backend_names = ["counting"]
        mgr.init_stt_backend("counting")

        audio = np.zeros(1600, dtype=np.int16)

        # First call — should try and fail
        core._try_stt_backends(audio)
        assert call_count == 1
        assert "counting" in core._failed_stt_backends

        # Second call — should be skipped entirely
        core._try_stt_backends(audio)
        assert call_count == 1  # NOT incremented

    def test_settings_change_clears_cache(self):
        """Changing settings should clear the failure cache, allowing retry."""
        core = self._make_core(stt_backend="failing")
        mgr = core.component_manager
        mgr._stt_modules = {"failing": _FailingSTT, "good": _GoodSTT}
        mgr.stt_backend_names = ["failing"]
        mgr.init_stt_backend("failing")

        audio = np.zeros(1600, dtype=np.int16)
        core._try_stt_backends(audio)
        assert "failing" in core._failed_stt_backends

        # Simulate settings change
        core._on_component_settings_changed("stt")
        assert len(core._failed_stt_backends) == 0

