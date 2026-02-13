"""Tests for HubConnectionManager reconnection and skill registration context."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from strawberry.spoke_core.hub_connection_manager import HubConnectionManager


class _DummySkillService:
    """Minimal skill service test double."""


async def _noop_emit(_: Any) -> None:
    """No-op event emitter for HubConnectionManager tests."""


@pytest.mark.asyncio
async def test_connect_retains_skill_service_when_token_missing() -> None:
    """connect() should retain skill_service even if connection is skipped."""

    def get_setting(key: str, default: Any) -> Any:
        if key == "hub.token":
            return ""
        return default

    manager = HubConnectionManager(
        get_setting=get_setting,
        emit=_noop_emit,
        get_loop=lambda: asyncio.get_running_loop(),
    )
    skill_service = _DummySkillService()

    connected = await manager.connect(skill_service=skill_service)

    assert connected is False
    assert manager._skill_service is skill_service


@pytest.mark.asyncio
async def test_schedule_reconnection_passes_retained_skill_service() -> None:
    """schedule_reconnection should reconnect using retained skill_service."""

    def get_setting(_: str, default: Any) -> Any:
        return default

    manager = HubConnectionManager(
        get_setting=get_setting,
        emit=_noop_emit,
        get_loop=lambda: asyncio.get_running_loop(),
    )
    skill_service = _DummySkillService()

    manager.disconnect = AsyncMock()
    manager.connect = AsyncMock(return_value=True)

    manager.schedule_reconnection(skill_service=skill_service)
    await asyncio.sleep(0.05)

    manager.disconnect.assert_awaited_once()
    manager.connect.assert_awaited_once_with(skill_service=skill_service)
