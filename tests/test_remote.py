"""Tests for remote skill execution."""

from unittest.mock import AsyncMock, Mock

import pytest

from strawberry.skills.remote import (
    LOCAL_MODE_PROMPT,
    REMOTE_MODE_PROMPT,
    SWITCHED_TO_LOCAL_PROMPT,
    SWITCHED_TO_REMOTE_PROMPT,
    DeviceManager,
    RemoteDeviceProxy,
    RemoteSkillClassProxy,
    RemoteSkillProxy,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_hub_client():
    """Create a mock Hub client."""
    client = Mock()
    # New grouped format: skills grouped by (class, method) with device list
    client.search_skills = AsyncMock(
        return_value=[
            {
                "path": "MediaSkill.set_volume",
                "signature": "set_volume(volume: int) -> None",
                "summary": "Set the TV volume (0-100).",
                "docstring": "Set the TV volume (0-100).",
                "devices": ["tv"],
                "device_names": ["TV"],
                "device_count": 1,
                "is_local": False,
            },
            {
                "path": "MediaSkill.play",
                "signature": "play(url: str) -> bool",
                "summary": "Play media from URL.",
                "docstring": "Play media from URL.",
                "devices": ["speaker"],
                "device_names": ["Speaker"],
                "device_count": 1,
                "is_local": False,
            },
            {
                "path": "TimeSkill.get_time",
                "signature": "get_time() -> str",
                "summary": "Get the current time.",
                "docstring": "Get the current time.",
                "devices": ["mydevice"],
                "device_names": ["MyDevice"],
                "device_count": 1,
                "is_local": True,
            },
        ]
    )
    client.execute_remote_skill = AsyncMock(return_value="Success!")
    return client


@pytest.fixture
def device_manager(mock_hub_client):
    """Create a DeviceManager with mock client."""
    return DeviceManager(mock_hub_client, local_device_name="MyDevice")


# =============================================================================
# DeviceManager Tests
# =============================================================================


class TestDeviceManager:
    """Tests for DeviceManager."""

    def test_init(self, mock_hub_client):
        """Should initialize with hub client and device name."""
        dm = DeviceManager(mock_hub_client, "TestDevice")
        assert dm._hub_client is mock_hub_client
        assert dm._local_device_name == "TestDevice"

    def test_search_skills_empty(self, device_manager):
        """Should return all skills when query is empty."""
        results = device_manager.search_skills()

        assert len(results) == 3
        # Local skills should be prioritized (first in results)
        local_skills = [r for r in results if r.get("is_local")]
        assert len(local_skills) == 1
        # Check local skill comes before other devices
        local_idx = next(i for i, r in enumerate(results) if r.get("is_local"))
        assert local_idx == 0  # Should be first

    def test_search_skills_with_query(self, device_manager):
        """Should filter skills by query."""
        results = device_manager.search_skills("volume")

        assert len(results) == 1
        assert results[0]["path"] == "MediaSkill.set_volume"

    def test_search_skills_cache(self, device_manager, mock_hub_client):
        """Should cache skill results."""
        # First call
        device_manager.search_skills()

        # Second call should use cache
        device_manager.search_skills()

        # search_skills should only be called once
        assert mock_hub_client.search_skills.call_count == 1

    def test_invalidate_cache(self, device_manager, mock_hub_client):
        """Should invalidate cache."""
        device_manager.search_skills()
        device_manager.invalidate_cache()
        device_manager.search_skills()

        # search_skills should be called twice
        assert mock_hub_client.search_skills.call_count == 2

    def test_describe_function_valid(self, device_manager):
        """Should return function description."""
        result = device_manager.describe_function("MediaSkill.set_volume")

        assert "set_volume" in result
        assert "volume" in result

    def test_describe_function_invalid_path(self, device_manager):
        """Should return error for invalid path (needs 2 parts)."""
        result = device_manager.describe_function("Invalid")

        assert "Invalid path" in result

    def test_describe_function_not_found(self, device_manager):
        """Should return error for unknown function."""
        result = device_manager.describe_function("Unknown.method")

        assert "not found" in result

    def test_getattr_returns_device_proxy(self, device_manager):
        """Should return device proxy for attribute access."""
        proxy = device_manager.TV

        assert isinstance(proxy, RemoteDeviceProxy)

    def test_getattr_caches_proxies(self, device_manager):
        """Should cache device proxies."""
        proxy1 = device_manager.TV
        proxy2 = device_manager.TV

        assert proxy1 is proxy2

    def test_getattr_rejects_private(self, device_manager):
        """Should reject private attributes."""
        with pytest.raises(AttributeError):
            _ = device_manager._private


# =============================================================================
# RemoteDeviceProxy Tests
# =============================================================================


class TestRemoteDeviceProxy:
    """Tests for RemoteDeviceProxy."""

    def test_getattr_returns_skill_proxy(self, device_manager):
        """Should return skill class proxy."""
        proxy = device_manager.TV.MediaSkill

        assert isinstance(proxy, RemoteSkillClassProxy)

    def test_getattr_rejects_private(self, device_manager):
        """Should reject private attributes."""
        with pytest.raises(AttributeError):
            _ = device_manager.TV._private


# =============================================================================
# RemoteSkillClassProxy Tests
# =============================================================================


class TestRemoteSkillClassProxy:
    """Tests for RemoteSkillClassProxy."""

    def test_getattr_returns_method_proxy(self, device_manager):
        """Should return method proxy."""
        proxy = device_manager.TV.MediaSkill.set_volume

        assert isinstance(proxy, RemoteSkillProxy)

    def test_getattr_rejects_private(self, device_manager):
        """Should reject private methods."""
        with pytest.raises(AttributeError):
            _ = device_manager.TV.MediaSkill._private


# =============================================================================
# RemoteSkillProxy Tests
# =============================================================================


class TestRemoteSkillProxy:
    """Tests for RemoteSkillProxy."""

    def test_call_executes_remote(self, device_manager, mock_hub_client):
        """Should execute remote skill via hub."""
        result = device_manager.TV.MediaSkill.set_volume(50)

        assert result == "Success!"
        mock_hub_client.execute_remote_skill.assert_called_once_with(
            device_name="TV",
            skill_name="MediaSkill",
            method_name="set_volume",
            args=[50],
            kwargs={},
        )

    def test_call_with_kwargs(self, device_manager, mock_hub_client):
        """Should pass kwargs to remote execution."""
        device_manager.Speaker.MediaSkill.play(url="http://example.com")

        mock_hub_client.execute_remote_skill.assert_called_once_with(
            device_name="Speaker",
            skill_name="MediaSkill",
            method_name="play",
            args=[],
            kwargs={"url": "http://example.com"},
        )


# =============================================================================
# Mode Prompt Tests
# =============================================================================


class TestModePrompts:
    """Tests for mode switching prompts."""

    def test_remote_mode_prompt_exists(self):
        """Should have remote mode prompt with devices.* syntax."""
        assert "devices." in REMOTE_MODE_PROMPT
        assert "search_skills" in REMOTE_MODE_PROMPT

    def test_local_mode_prompt_exists(self):
        """Should have local mode prompt with device.* syntax."""
        assert "device." in LOCAL_MODE_PROMPT
        assert "search_skills" in LOCAL_MODE_PROMPT

    def test_switched_to_remote_prompt(self):
        """Should have switch-to-online prompt with devices.* syntax."""
        assert "ONLINE" in SWITCHED_TO_REMOTE_PROMPT
        assert "devices." in SWITCHED_TO_REMOTE_PROMPT

    def test_switched_to_local_prompt(self):
        """Should have switch-to-local prompt with device.* syntax."""
        assert "LOCAL" in SWITCHED_TO_LOCAL_PROMPT
        assert "device." in SWITCHED_TO_LOCAL_PROMPT
