"""Weather skill with real API integration and proper error handling."""

import logging
import os
from datetime import datetime
from typing import Any, Dict

import requests

logger = logging.getLogger(__name__)


class WeatherSkill:
    """Provides weather data with explicit configuration requirements."""

    def __init__(self):
        self._base_url = "https://api.openweathermap.org/data/2.5"
        self._geo_url = "https://api.openweathermap.org/geo/1.0"

        self._us_state_codes = {
            "AL",
            "AK",
            "AZ",
            "AR",
            "CA",
            "CO",
            "CT",
            "DE",
            "FL",
            "GA",
            "HI",
            "ID",
            "IL",
            "IN",
            "IA",
            "KS",
            "KY",
            "LA",
            "ME",
            "MD",
            "MA",
            "MI",
            "MN",
            "MS",
            "MO",
            "MT",
            "NE",
            "NV",
            "NH",
            "NJ",
            "NM",
            "NY",
            "NC",
            "ND",
            "OH",
            "OK",
            "OR",
            "PA",
            "RI",
            "SC",
            "SD",
            "TN",
            "TX",
            "UT",
            "VT",
            "VA",
            "WA",
            "WV",
            "WI",
            "WY",
            "DC",
        }

    def _get_api_key(self) -> str:
        api_key = os.environ.get("WEATHER_API_KEY")
        if not api_key:
            raise ValueError("Weather API not configured")
        return api_key

    def _normalize_location(self, location: str) -> str:
        raw = (location or "").strip()
        if not raw:
            raise ValueError("Location is required")

        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if len(parts) == 1:
            return parts[0]

        if len(parts) == 2:
            city, second = parts
            second_upper = second.upper()
            if second_upper in self._us_state_codes:
                return f"{city},{second_upper},US"
            return f"{city},{second_upper}"

        city = parts[0]
        state = parts[1].upper()
        country = parts[2].upper()
        return f"{city},{state},{country}"

    def _geocode(self, location: str, api_key: str) -> Dict[str, Any]:
        query = self._normalize_location(location)
        params = {
            "q": query,
            "limit": 1,
            "appid": api_key,
        }

        response = requests.get(
            f"{self._geo_url}/direct",
            params=params,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list) or not data:
            raise ValueError(f"Location not found: {location}")
        top = data[0]
        if "lat" not in top or "lon" not in top:
            raise ValueError(f"Location not found: {location}")
        return top

    def get_current_weather(self, location: str, units: str = "metric") -> Dict[str, Any]:
        """Get current weather with clear status."""
        try:
            api_key = self._get_api_key()
        except Exception:
            return {
                "success": False,
                "error": "Weather API not configured",
                "message": "Please set WEATHER_API_KEY environment variable",
                "documentation": "https://openweathermap.org/api",
            }

        try:
            return self._fetch_weather_data(location, units, api_key)
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": "Weather data unavailable",
                "location": location,
                "suggested_action": "Check API key and network connection",
            }

    def _fetch_weather_data(
        self, location: str, units: str, api_key: str
    ) -> Dict[str, Any]:
        """Fetch real weather data."""
        geo = self._geocode(location, api_key)
        params = {
            "lat": geo["lat"],
            "lon": geo["lon"],
            "units": units,
            "appid": api_key,
        }

        response = requests.get(f"{self._base_url}/weather", params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("cod") != 200:
            raise Exception(f"API error: {data.get('message', 'Unknown error')}")

        return {
            "success": True,
            "location": f"{data['name']}, {data['sys']['country']}",
            "temperature": data["main"]["temp"],
            "conditions": data["weather"][0]["description"],
            "humidity": data["main"]["humidity"],
            "wind_speed": data["wind"]["speed"],
            "source": "OpenWeatherMap",
            "timestamp": datetime.now().isoformat(),
        }

    def get_forecast(
        self, location: str, days: int = 5, units: str = "metric"
    ) -> Dict[str, Any]:
        """Get weather forecast with clear status."""
        try:
            api_key = self._get_api_key()
        except Exception:
            return {
                "success": False,
                "error": "Weather API not configured",
                "message": "Please set WEATHER_API_KEY environment variable",
                "documentation": "https://openweathermap.org/api",
            }

        try:
            return self._fetch_forecast_data(location, days, units, api_key)
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": "Weather forecast unavailable",
                "location": location,
                "days": days,
                "suggested_action": "Check API key and network connection",
            }

    def _fetch_forecast_data(
        self, location: str, days: int, units: str, api_key: str
    ) -> Dict[str, Any]:
        """Fetch real forecast data."""
        normalized = self._normalize_location(location)
        params = {"q": normalized, "units": units, "appid": api_key, "cnt": min(days, 16)}

        response = requests.get(
            f"{self._base_url}/forecast/daily", params=params, timeout=15
        )
        response.raise_for_status()
        data = response.json()

        if data.get("cod") != 200:
            raise Exception(f"API error: {data.get('message', 'Unknown error')}")

        forecast = []
        for day_data in data["list"][:days]:
            forecast.append(
                {
                    "date": datetime.fromtimestamp(day_data["dt"]).strftime("%Y-%m-%d"),
                    "day_of_week": datetime.fromtimestamp(day_data["dt"]).strftime("%A"),
                    "temperature": day_data["temp"]["day"],
                    "min_temp": day_data["temp"]["min"],
                    "max_temp": day_data["temp"]["max"],
                    "conditions": day_data["weather"][0]["description"],
                    "humidity": day_data.get("humidity", 0),
                    "wind_speed": day_data.get("speed", 0),
                    "precipitation_probability": round(day_data.get("pop", 0) * 100, 1),
                }
            )

        return {
            "success": True,
            "forecast": forecast,
            "location": f"{data['city']['name']}, {data['city']['country']}",
            "source": "OpenWeatherMap",
            "days": len(forecast),
        }
