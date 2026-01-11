"""Tests for online/offline skill mode behavior.

These tests ensure that:
- The system prompt teaches the LLM to use `device` in local mode.
- The system prompt teaches the LLM to use `devices` in remote mode.
- When forced into local mode (fallback/offline), the skill service does not
  attempt to call Hub APIs for tool execution.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from strawberry.skills.sandbox.proxy_gen import SkillMode
from strawberry.skills.service import SkillService


class _StubSyncHubClient:
    def __init__(self) -> None:
        self.execute_calls: list[tuple[str, str, str, list[Any], dict[str, Any]]] = []
        self.search_calls: list[tuple[str, int]] = []

    def execute_remote_skill_sync(
        self,
        device_name: str,
        skill_name: str,
        method_name: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        self.execute_calls.append(
            (device_name, skill_name, method_name, list(args or []), dict(kwargs or {}))
        )
        return "stub-remote-result"

    def search_skills_sync(self, query: str = "", device_limit: int = 10) -> list[dict[str, Any]]:
        self.search_calls.append((query, device_limit))
        return []


def _write_min_skill(skills_dir: Path) -> None:
    skills_dir.mkdir(parents=True, exist_ok=True)
    repo_dir = skills_dir / "demo_skill"
    repo_dir.mkdir(parents=True, exist_ok=True)
    (repo_dir / "skill.py").write_text(
        """

class DemoSkill:
    '''Demo skill.'''

    def ping(self) -> str:
        return "pong"
""".lstrip()
    )


def test_system_prompt_local_mode_uses_device(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    _write_min_skill(skills_dir)

    svc = SkillService(skills_path=skills_dir, hub_client=None, use_sandbox=False)
    svc.load_skills()

    prompt = svc.get_system_prompt()
    assert "Runtime mode: OFFLINE/LOCAL." in prompt
    assert "device.DemoSkill.ping" in prompt


def test_system_prompt_remote_mode_uses_devices(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    _write_min_skill(skills_dir)

    hub_client = AsyncMock()
    svc = SkillService(skills_path=skills_dir, hub_client=hub_client, use_sandbox=False)
    svc.load_skills()

    svc.set_mode_override(SkillMode.REMOTE)
    prompt = svc.get_system_prompt()

    assert "Runtime mode: ONLINE (Hub)." in prompt
    assert "devices." in prompt


@pytest.mark.asyncio
async def test_execute_tool_async_does_not_call_hub_when_forced_local(
    tmp_path: Path,
) -> None:
    skills_dir = tmp_path / "skills"
    _write_min_skill(skills_dir)

    hub_client = AsyncMock()
    svc = SkillService(skills_path=skills_dir, hub_client=hub_client, use_sandbox=False)
    svc.load_skills()

    svc.set_mode_override(SkillMode.LOCAL)

    res: dict[str, Any] = await svc.execute_tool_async(
        "search_skills",
        {"query": "ping", "device_limit": 10},
    )

    assert "result" in res
    hub_client.search_skills.assert_not_awaited()


@pytest.mark.asyncio
async def test_local_device_works_without_sandbox(tmp_path: Path) -> None:
    """Local device calls should work without Deno (direct execution fallback)."""
    skills_dir = tmp_path / "skills"
    _write_min_skill(skills_dir)

    hub_client = AsyncMock()
    # Device name will be normalized to "my_strawberry_spoke"
    svc = SkillService(
        skills_path=skills_dir,
        hub_client=hub_client,
        use_sandbox=False,
        device_name="My Strawberry Spoke",
    )
    svc.load_skills()

    result = svc.execute_code("print(device.DemoSkill.ping())")
    assert result.success is True
    assert result.result == "pong"


@pytest.mark.asyncio
async def test_local_device_via_devices_syntax_in_remote_mode(tmp_path: Path) -> None:
    """Local device calls via devices.<local_device>.* should execute locally, not via Hub."""
    skills_dir = tmp_path / "skills"
    _write_min_skill(skills_dir)

    hub_client = _StubSyncHubClient()
    svc = SkillService(
        skills_path=skills_dir,
        hub_client=hub_client,
        use_sandbox=False,
        device_name="My Strawberry Spoke",
    )
    svc.load_skills()

    # Call local device using devices.my_strawberry_spoke.* syntax in REMOTE mode
    # This should execute locally without Hub roundtrip
    result = svc.execute_code(
        "print(devices.my_strawberry_spoke.DemoSkill.ping())"
    )
    assert result.success is True
    assert result.result == "pong"  # Local execution returns "pong", not "stub-remote-result"
    assert not hub_client.execute_calls  # Should NOT have called Hub


@pytest.mark.asyncio
async def test_remote_device_works_without_sandbox_via_sync_hub(tmp_path: Path) -> None:
    """Remote device calls should work without Deno via the sync HubClient path."""
    skills_dir = tmp_path / "skills"
    _write_min_skill(skills_dir)

    hub_client = _StubSyncHubClient()
    svc = SkillService(
        skills_path=skills_dir,
        hub_client=hub_client,
        use_sandbox=False,
        device_name="My Strawberry Spoke",
    )
    svc.load_skills()

    # Remote device call (different device) should execute via hub sync method
    result = svc.execute_code(
        "print(devices.living_room_pc.DemoSkill.ping())"
    )
    assert result.success is True
    assert result.result == "stub-remote-result"
    assert hub_client.execute_calls


@pytest.mark.asyncio
async def test_device_manager_works_without_sandbox_via_sync_hub(tmp_path: Path) -> None:
    """device_manager calls should work without Deno via the sync HubClient path."""
    skills_dir = tmp_path / "skills"
    _write_min_skill(skills_dir)

    hub_client = _StubSyncHubClient()
    svc = SkillService(skills_path=skills_dir, hub_client=hub_client, use_sandbox=False)
    svc.load_skills()

    result = svc.execute_code("print(device_manager.search_skills(query='ping'))")
    assert result.success is True
    assert result.result == "[]"
    assert hub_client.search_calls


@pytest.mark.asyncio
async def test_offline_mode_blocks_remote_proxy_usage(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    _write_min_skill(skills_dir)

    hub_client = _StubSyncHubClient()
    svc = SkillService(skills_path=skills_dir, hub_client=hub_client, use_sandbox=False)
    svc.load_skills()
    svc.set_mode_override(SkillMode.LOCAL)

    result = svc.execute_code("print(devices.other_pc.DemoSkill.ping())")
    assert result.success is False
    assert result.error
    assert "OFFLINE/LOCAL" in result.error
