"""Tests for STT module discovery."""

import pytest

from strawberry.stt import (
    STTEngine,
    discover_stt_modules,
    get_stt_module,
    list_stt_modules,
)
from strawberry.stt.backends.mock import MockSTT


class TestDiscoverSttModules:
    """Tests for discover_stt_modules function."""
    
    def test_discovers_mock_module(self):
        """Should discover the mock STT module."""
        modules = discover_stt_modules()
        assert "mock" in modules
        assert modules["mock"] is MockSTT
    
    def test_all_modules_are_stt_engines(self):
        """All discovered modules should be STTEngine subclasses."""
        modules = discover_stt_modules()
        for name, cls in modules.items():
            assert issubclass(cls, STTEngine), f"{name} is not an STTEngine subclass"
    
    def test_modules_have_metadata(self):
        """All discovered modules should have name and description."""
        modules = discover_stt_modules()
        for name, cls in modules.items():
            assert hasattr(cls, "name"), f"{name} missing 'name' attribute"
            assert hasattr(cls, "description"), f"{name} missing 'description' attribute"


class TestGetSttModule:
    """Tests for get_stt_module function."""
    
    def test_get_existing_module(self):
        """Should return the module class for a valid name."""
        module = get_stt_module("mock")
        assert module is MockSTT
    
    def test_get_nonexistent_module(self):
        """Should return None for unknown module name."""
        module = get_stt_module("nonexistent_module_xyz")
        assert module is None


class TestListSttModules:
    """Tests for list_stt_modules function."""
    
    def test_returns_list(self):
        """Should return a list of module info dictionaries."""
        modules = list_stt_modules()
        assert isinstance(modules, list)
        assert len(modules) > 0
    
    def test_module_info_structure(self):
        """Each module info should have required fields."""
        modules = list_stt_modules()
        for info in modules:
            assert "name" in info
            assert "display_name" in info
            assert "description" in info
            assert "has_settings" in info
    
    def test_mock_module_in_list(self):
        """Mock module should be in the list."""
        modules = list_stt_modules()
        mock_info = next((m for m in modules if m["name"] == "mock"), None)
        assert mock_info is not None
        assert mock_info["display_name"] == "Mock STT"


class TestSttEngineSettingsSchema:
    """Tests for STTEngine get_settings_schema method."""
    
    def test_mock_has_no_settings(self):
        """MockSTT should have no configurable settings."""
        schema = MockSTT.get_settings_schema()
        assert schema == []
    
    def test_leopard_has_settings(self):
        """LeopardSTT should have configurable settings."""
        from strawberry.stt.backends.leopard import LeopardSTT
        
        schema = LeopardSTT.get_settings_schema()
        assert len(schema) > 0
        
        # Check for expected fields
        keys = [f.key for f in schema]
        assert "access_key" in keys
    
    def test_leopard_settings_are_valid(self):
        """LeopardSTT settings should be valid SettingField objects."""
        from strawberry.core.settings_schema import SettingField
        from strawberry.stt.backends.leopard import LeopardSTT
        
        schema = LeopardSTT.get_settings_schema()
        for field in schema:
            assert isinstance(field, SettingField)
    
    def test_get_default_settings(self):
        """get_default_settings should return defaults from schema."""
        from strawberry.stt.backends.leopard import LeopardSTT
        
        defaults = LeopardSTT.get_default_settings()
        assert isinstance(defaults, dict)
        # model_path has a default of ""
        assert "model_path" in defaults
