"""Tests for disabled-skill enforcement across all execution paths.

Verifies that once a skill is disabled via SkillService.disable_skill(),
it cannot be:
- Executed via execute_skill_by_name (WebSocket / native tool)
- Found via search_skills
- Described via describe_function
- Accessed via DeviceProxy (python_exec)
- Registered with the Hub
"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from strawberry.skills.loader import SkillLoader
from strawberry.skills.proxies import DeviceProxy
from strawberry.skills.service import SkillService

# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture()
def skills_dir():
    """Create a temp skills directory with two test skills."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skill_file = Path(tmpdir) / "test_skills.py"
        skill_file.write_text(
            '''\
class AlphaSkill:
    """First test skill."""

    def greet(self, name: str = "world") -> str:
        """Say hello."""
        return f"Hello, {name}!"


class BetaSkill:
    """Second test skill."""

    def farewell(self) -> str:
        """Say goodbye."""
        return "Goodbye!"
'''
        )
        yield Path(tmpdir)


@pytest.fixture()
def service(skills_dir):
    """Create a SkillService with test skills loaded."""
    svc = SkillService(skills_path=skills_dir, use_sandbox=False)
    svc.load_skills()
    return svc


@pytest.fixture()
def loader(skills_dir):
    """Create a SkillLoader with test skills loaded."""
    ldr = SkillLoader(skills_dir)
    ldr.load_all()
    return ldr


# ── execute_skill_by_name ───────────────────────────────────────────


class TestDisabledSkillExecution:
    """Disabled skills must be rejected by execute_skill_by_name."""

    @pytest.mark.asyncio
    async def test_execute_disabled_skill_raises(self, service):
        """Executing a disabled skill should raise ValueError."""
        service.disable_skill("AlphaSkill")
        with pytest.raises(ValueError, match="disabled"):
            await service.execute_skill_by_name(
                "AlphaSkill", "greet", [], {}
            )

    @pytest.mark.asyncio
    async def test_execute_enabled_skill_works(self, service):
        """An enabled skill should execute normally."""
        result = await service.execute_skill_by_name(
            "AlphaSkill", "greet", [], {"name": "test"}
        )
        assert result == "Hello, test!"


# ── _execute_native_tool ────────────────────────────────────────────


class TestDisabledNativeTool:
    """Disabled skills must be rejected by native tool dispatch."""

    @pytest.mark.asyncio
    async def test_native_tool_disabled_skill(self, service):
        """Native tool call on disabled skill returns error dict."""
        service.disable_skill("AlphaSkill")
        result = await service.execute_tool_async(
            "AlphaSkill__greet", {"name": "test"}
        )
        assert "error" in result
        assert "disabled" in result["error"]


# ── search_skills ───────────────────────────────────────────────────


class TestDisabledSkillSearch:
    """Disabled skills must not appear in search results."""

    def test_search_excludes_disabled(self, service):
        """search_skills should omit disabled skills."""
        service.disable_skill("AlphaSkill")
        result = service.execute_tool("search_skills", {"query": ""})
        assert "AlphaSkill" not in result.get("result", "")
        # BetaSkill should still be present
        assert "BetaSkill" in result.get("result", "")

    def test_search_includes_when_enabled(self, service):
        """Both skills should appear when none are disabled."""
        result = service.execute_tool("search_skills", {"query": ""})
        output = result.get("result", "")
        assert "AlphaSkill" in output
        assert "BetaSkill" in output


# ── describe_function ───────────────────────────────────────────────


class TestDisabledSkillDescribe:
    """Disabled skills must not be describable."""

    def test_describe_disabled_skill(self, service):
        """describe_function on a disabled skill should return error."""
        service.disable_skill("AlphaSkill")
        result = service.execute_tool(
            "describe_function", {"path": "AlphaSkill.greet"}
        )
        output = result.get("result", "")
        assert "disabled" in output.lower() or "Error" in output


# ── DeviceProxy ─────────────────────────────────────────────────────


class TestDisabledDeviceProxy:
    """DeviceProxy must block access to disabled skills."""

    def test_proxy_getattr_disabled_raises(self, loader):
        """Accessing a disabled skill via device.SkillName should raise."""
        proxy = DeviceProxy(loader, disabled_skills={"AlphaSkill"})
        with pytest.raises(AttributeError, match="disabled"):
            proxy.AlphaSkill  # noqa: B018 — intentional attribute access

    def test_proxy_getattr_enabled_works(self, loader):
        """Accessing an enabled skill should return a SkillProxy."""
        proxy = DeviceProxy(loader)
        # Should not raise
        skill_proxy = proxy.AlphaSkill
        assert skill_proxy is not None

    def test_proxy_search_excludes_disabled(self, loader):
        """search_skills should exclude disabled skills."""
        proxy = DeviceProxy(loader, disabled_skills={"AlphaSkill"})
        results = proxy.search_skills("")
        paths = [r["path"] for r in results]
        assert not any("AlphaSkill" in p for p in paths)
        assert any("BetaSkill" in p for p in paths)

    def test_proxy_describe_disabled(self, loader):
        """describe_function should reject disabled skills."""
        proxy = DeviceProxy(loader, disabled_skills={"AlphaSkill"})
        result = proxy.describe_function("AlphaSkill.greet")
        assert "disabled" in result.lower()


# ── register_with_hub ───────────────────────────────────────────────


class TestDisabledSkillRegistration:
    """Disabled skills must be excluded from hub registration."""

    @pytest.mark.asyncio
    async def test_registration_excludes_disabled(self, service):
        """Hub registration payload should omit disabled skills."""
        mock_client = AsyncMock()
        mock_client.register_skills = AsyncMock(return_value=True)
        service.hub_client = mock_client

        service.disable_skill("AlphaSkill")
        await service.register_with_hub()

        # Get what was sent to the Hub
        registered = mock_client.register_skills.call_args[0][0]
        class_names = {d["class_name"] for d in registered}
        assert "AlphaSkill" not in class_names
        assert "BetaSkill" in class_names
