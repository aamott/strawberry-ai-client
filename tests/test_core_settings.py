"""Tests for SpokeCore settings API."""

import pytest

from strawberry.spoke_core import (
    CORE_SETTINGS_SCHEMA,
    SettingField,
    SettingsChanged,
    SpokeCore,
)


class TestSpokeCoreSettingsApi:
    """Tests for SpokeCore settings methods."""

    @pytest.fixture
    def core(self):
        """Create a SpokeCore instance for testing."""
        return SpokeCore()

    def test_get_settings_schema(self, core):
        """get_settings_schema should return core settings schema."""
        schema = core.get_settings_schema()
        assert schema == CORE_SETTINGS_SCHEMA
        assert len(schema) > 0
        for field in schema:
            assert isinstance(field, SettingField)

    def test_get_settings_returns_dict(self, core):
        """get_settings should return a dictionary of current values."""
        settings = core.get_settings()
        assert isinstance(settings, dict)

        # Check expected keys exist
        assert "device.name" in settings
        assert "hub.url" in settings
        assert "skills.sandbox.enabled" in settings

    def test_get_settings_has_correct_types(self, core):
        """get_settings values should have correct types."""
        settings = core.get_settings()

        assert isinstance(settings["device.name"], str)
        assert isinstance(settings["hub.url"], str)
        assert isinstance(settings["skills.sandbox.enabled"], bool)

    def test_get_settings_options_models(self, core):
        """get_settings_options should return fallback models."""
        # This tests the fallback since Ollama likely isn't running
        options = core.get_settings_options("get_available_models")
        assert isinstance(options, list)
        assert len(options) > 0
        assert "llama3.2:3b" in options  # Fallback includes this

    def test_get_settings_options_unknown_provider(self, core):
        """get_settings_options should raise ValueError for unknown provider."""
        with pytest.raises(ValueError, match="Unknown options provider"):
            core.get_settings_options("unknown_provider")


class TestSettingsChangedEvent:
    """Tests for SettingsChanged event."""

    def test_settings_changed_with_keys(self):
        """SettingsChanged should include changed keys."""
        event = SettingsChanged(changed_keys=["device.name", "hub.url"])
        assert event.changed_keys == ["device.name", "hub.url"]

    def test_settings_changed_default_empty(self):
        """SettingsChanged should default to empty list."""
        event = SettingsChanged()
        assert event.changed_keys == []


@pytest.mark.asyncio
class TestSpokeCoreSettingsAsync:
    """Async tests for SpokeCore settings methods."""

    async def test_execute_settings_action_hub_oauth(self):
        """execute_settings_action should return ActionResult for hub_oauth."""
        from strawberry.spoke_core.settings_schema import ActionResult

        core = SpokeCore()
        result = await core.execute_settings_action("hub_oauth")

        assert isinstance(result, ActionResult)
        assert result.type == "open_browser"
        assert result.pending is True

    async def test_execute_settings_action_unknown(self):
        """execute_settings_action should raise ValueError for unknown action."""
        core = SpokeCore()

        with pytest.raises(ValueError, match="Unknown action"):
            await core.execute_settings_action("unknown_action")
