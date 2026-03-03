"""Tests for wakeword module discovery."""

from strawberry.voice.wakeword import (
    WakeWordDetector,
    discover_wake_modules,
    get_wake_module,
    list_wake_modules,
)
from strawberry.voice.wakeword.backends.mock import MockWakeWordDetector


class TestDiscoverWakeModules:
    """Tests for discover_wake_modules function."""

    def test_discovers_mock_module(self):
        modules = discover_wake_modules()
        assert "mock" in modules
        assert modules["mock"] is MockWakeWordDetector

    def test_all_modules_are_wake_detectors(self):
        modules = discover_wake_modules()
        for name, cls in modules.items():
            assert issubclass(cls, WakeWordDetector), (
                f"{name} is not a WakeWordDetector subclass"
            )

    def test_modules_have_metadata(self):
        modules = discover_wake_modules()
        for name, cls in modules.items():
            assert hasattr(cls, "name"), f"{name} missing 'name' attribute"
            assert hasattr(cls, "description"), f"{name} missing 'description' attribute"


class TestGetWakeModule:
    """Tests for get_wake_module function."""

    def test_get_existing_module(self):
        module = get_wake_module("mock")
        assert module is MockWakeWordDetector

    def test_get_nonexistent_module(self):
        module = get_wake_module("nonexistent_module_xyz")
        assert module is None


class TestListWakeModules:
    """Tests for list_wake_modules function."""

    def test_returns_list(self):
        modules = list_wake_modules()
        assert isinstance(modules, list)
        assert len(modules) > 0

    def test_module_info_structure(self):
        modules = list_wake_modules()
        for info in modules:
            assert "name" in info
            assert "display_name" in info
            assert "description" in info
            assert "has_settings" in info

    def test_mock_module_in_list(self):
        modules = list_wake_modules()
        mock_info = next((m for m in modules if m["name"] == "mock"), None)
        assert mock_info is not None
        assert mock_info["display_name"] == "Mock Wake Word"


class TestWakeBackendsMatchSettings:
    """Ensure discovered wake backends are allowed in config settings."""

    def test_discovered_backends_are_allowed_in_settings(self):
        from typing import get_args

        from strawberry.config.settings import WakeWordSettings

        discovered = discover_wake_modules()
        backend_field = WakeWordSettings.model_fields["backend"]
        allowed_backends = get_args(backend_field.annotation)

        for backend_name in discovered.keys():
            assert backend_name in allowed_backends, (
                f"Wake backend '{backend_name}' was discovered but is not in "
                f"WakeWordSettings.backend Literal type. Add it to settings.py!"
            )


class TestDaVoiceHealth:
    """DaVoice-specific health checks."""

    def test_davoice_health_matches_availability(self):
        from strawberry.voice.wakeword.backends.davoice import (
            _DAVOICE_AVAILABLE,
            DaVoiceDetector,
        )

        assert DaVoiceDetector.is_healthy() == _DAVOICE_AVAILABLE
        if not _DAVOICE_AVAILABLE:
            error = DaVoiceDetector.health_check_error()
            assert error is not None
            assert "keyword_detection" in error.lower() or "davoice" in error.lower()
