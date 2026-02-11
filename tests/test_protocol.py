"""Tests for wire protocol parity: device name normalization and version header."""

import json
from pathlib import Path

import pytest

from strawberry.hub.client import PROTOCOL_VERSION, PROTOCOL_VERSION_HEADER, HubConfig
from strawberry.skills.service import normalize_device_name

# ── Normalization parity tests ──────────────────────────────────────────────

FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]  # repo root
    / "docs"
    / "test-fixtures"
    / "normalize_device_name.json"
)


def _load_normalization_cases() -> list:
    """Load test vectors from the shared fixture file."""
    data = json.loads(FIXTURE_PATH.read_text())
    return data["cases"]


@pytest.mark.parametrize(
    "case",
    _load_normalization_cases(),
    ids=[c["input"] or "<empty>" for c in _load_normalization_cases()],
)
def test_normalize_device_name(case: dict):
    """Spoke normalize_device_name must match the canonical fixture."""
    assert normalize_device_name(case["input"]) == case["expected"]


# ── Protocol version header tests ──────────────────────────────────────────


def test_protocol_version_constant():
    """PROTOCOL_VERSION must be v1 (current wire schema)."""
    assert PROTOCOL_VERSION == "v1"


def test_protocol_version_header_name():
    """Header name must match what Hub middleware expects."""
    assert PROTOCOL_VERSION_HEADER == "X-Protocol-Version"


def test_hub_client_sets_version_header():
    """HubClient HTTP clients include the protocol version header."""
    from strawberry.hub.client import HubClient

    config = HubConfig(url="http://localhost:8000", token="test")
    client = HubClient(config)

    # Async client
    async_headers = client.client.headers
    assert async_headers.get(PROTOCOL_VERSION_HEADER) == PROTOCOL_VERSION

    # Sync client
    sync_headers = client.sync_client.headers
    assert sync_headers.get(PROTOCOL_VERSION_HEADER) == PROTOCOL_VERSION

    # Cleanup (sync only; async requires await)
    client.sync_client.close()
