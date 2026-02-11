"""Tests for WeatherSkill."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock, patch

import pytest

from skills.weather_skill.skill import WeatherSkill


def _make_response(*, json_data: Any) -> Mock:
    response = Mock()
    response.raise_for_status = Mock()
    response.json = Mock(return_value=json_data)
    return response


def test_get_current_weather_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """If WEATHER_API_KEY is missing, the skill returns a helpful error object."""
    monkeypatch.delenv("WEATHER_API_KEY", raising=False)

    skill = WeatherSkill()
    result = skill.get_current_weather("roy, ut")

    assert result["success"] is False
    assert result["error"] == "Weather API not configured"


def test_get_current_weather_geocodes_and_uses_lat_lon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Current weather uses geocoding and then queries weather by lat/lon."""
    monkeypatch.setenv("WEATHER_API_KEY", "test-key")

    skill = WeatherSkill()

    geo_response = _make_response(
        json_data=[{"name": "Roy", "lat": 41.16, "lon": -112.03, "country": "US"}]
    )
    weather_response = _make_response(
        json_data={
            "cod": 200,
            "name": "Roy",
            "sys": {"country": "US"},
            "main": {"temp": 10.0, "humidity": 50},
            "weather": [{"description": "clear sky"}],
            "wind": {"speed": 3.0},
        }
    )

    with patch(
        "skills.weather_skill.skill.requests.get",
        side_effect=[geo_response, weather_response],
    ) as mock_get:
        result = skill.get_current_weather("roy, ut")

    assert result["success"] is True
    assert result["location"] == "Roy, US"
    assert result["temperature"] == 10.0

    assert mock_get.call_count == 2

    geo_call = mock_get.call_args_list[0]
    weather_call = mock_get.call_args_list[1]

    assert geo_call.kwargs["params"]["q"] == "roy,UT,US"
    assert geo_call.kwargs["params"]["appid"] == "test-key"

    assert weather_call.kwargs["params"]["lat"] == 41.16
    assert weather_call.kwargs["params"]["lon"] == -112.03
    assert weather_call.kwargs["params"]["appid"] == "test-key"


def test_get_current_weather_location_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """If geocoding returns no results, the skill returns a failure object."""
    monkeypatch.setenv("WEATHER_API_KEY", "test-key")

    skill = WeatherSkill()

    geo_response = _make_response(json_data=[])

    with patch("skills.weather_skill.skill.requests.get", return_value=geo_response):
        result = skill.get_current_weather("nowhereville, ut")

    assert result["success"] is False
    assert result["message"] == "Weather data unavailable"
    assert "Location not found" in result["error"]
