"""Tests for TTS module discovery."""

import pytest

from strawberry.tts import (
    TTSEngine,
    discover_tts_modules,
    get_tts_module,
    list_tts_modules,
)
from strawberry.tts.backends.mock import MockTTS


class TestDiscoverTtsModules:
    """Tests for discover_tts_modules function."""
    
    def test_discovers_mock_module(self):
        """Should discover the mock TTS module."""
        modules = discover_tts_modules()
        assert "mock" in modules
        assert modules["mock"] is MockTTS
    
    def test_all_modules_are_tts_engines(self):
        """All discovered modules should be TTSEngine subclasses."""
        modules = discover_tts_modules()
        for name, cls in modules.items():
            assert issubclass(cls, TTSEngine), f"{name} is not a TTSEngine subclass"
    
    def test_modules_have_metadata(self):
        """All discovered modules should have name and description."""
        modules = discover_tts_modules()
        for name, cls in modules.items():
            assert hasattr(cls, "name"), f"{name} missing 'name' attribute"
            assert hasattr(cls, "description"), f"{name} missing 'description' attribute"


class TestGetTtsModule:
    """Tests for get_tts_module function."""
    
    def test_get_existing_module(self):
        """Should return the module class for a valid name."""
        module = get_tts_module("mock")
        assert module is MockTTS
    
    def test_get_nonexistent_module(self):
        """Should return None for unknown module name."""
        module = get_tts_module("nonexistent_module_xyz")
        assert module is None


class TestListTtsModules:
    """Tests for list_tts_modules function."""
    
    def test_returns_list(self):
        """Should return a list of module info dictionaries."""
        modules = list_tts_modules()
        assert isinstance(modules, list)
        assert len(modules) > 0
    
    def test_module_info_structure(self):
        """Each module info should have required fields."""
        modules = list_tts_modules()
        for info in modules:
            assert "name" in info
            assert "display_name" in info
            assert "description" in info
            assert "has_settings" in info
    
    def test_mock_module_in_list(self):
        """Mock module should be in the list."""
        modules = list_tts_modules()
        mock_info = next((m for m in modules if m["name"] == "mock"), None)
        assert mock_info is not None
        assert mock_info["display_name"] == "Mock TTS"


class TestTtsEngineSettingsSchema:
    """Tests for TTSEngine get_settings_schema method."""
    
    def test_mock_has_no_settings(self):
        """MockTTS should have no configurable settings."""
        schema = MockTTS.get_settings_schema()
        assert schema == []
    
    def test_orca_has_settings(self):
        """OrcaTTS should have configurable settings."""
        from strawberry.tts.backends.orca import OrcaTTS
        
        schema = OrcaTTS.get_settings_schema()
        assert len(schema) > 0
        
        # Check for expected fields
        keys = [f.key for f in schema]
        assert "access_key" in keys
    
    def test_orca_settings_are_valid(self):
        """OrcaTTS settings should be valid SettingField objects."""
        from strawberry.core.settings_schema import SettingField
        from strawberry.tts.backends.orca import OrcaTTS
        
        schema = OrcaTTS.get_settings_schema()
        for field in schema:
            assert isinstance(field, SettingField)
    
    def test_get_default_settings(self):
        """get_default_settings should return defaults from schema."""
        from strawberry.tts.backends.orca import OrcaTTS
        
        defaults = OrcaTTS.get_default_settings()
        assert isinstance(defaults, dict)
        # model_path has a default of ""
        assert "model_path" in defaults
