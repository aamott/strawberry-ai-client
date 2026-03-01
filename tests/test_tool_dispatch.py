"""Tests for mode-aware formatting in tool_dispatch.format_search_results.

Verifies that search results include native tool names when tool_mode='native'
and omit them when tool_mode='code' (default).
"""

from __future__ import annotations

from strawberry.skills.tool_dispatch import format_search_results


# ── Sample data ──────────────────────────────────────────────────────


def _make_results():
    """Build a small list of search result dicts for testing."""
    return [
        {
            "path": "WeatherSkill.get_current_weather",
            "signature": "get_current_weather(location: str = 'here') -> str",
            "summary": "Return the weather for a location.",
        },
        {
            "path": "CalcSkill.add",
            "signature": "add(a: int, b: int) -> int",
            "summary": "Add two numbers.",
        },
    ]


# ── Tests: code mode (default) ──────────────────────────────────────


class TestFormatSearchResultsCodeMode:
    """Verify format_search_results in code/python_exec mode."""

    def test_contains_result_paths(self):
        """Each result path should appear in the output."""
        output = format_search_results(_make_results())
        assert "WeatherSkill.get_current_weather" in output
        assert "CalcSkill.add" in output

    def test_no_native_tool_names(self):
        """Code mode should NOT include [tool: ...] annotations."""
        output = format_search_results(_make_results())
        assert "[tool:" not in output
        assert "__" not in output  # no double-underscore tool names

    def test_empty_results(self):
        """Empty result list should return a 'no results' message."""
        output = format_search_results([])
        assert "No results found" in output

    def test_result_count(self):
        """Output should mention the correct result count."""
        output = format_search_results(_make_results())
        assert "2 result(s)" in output


# ── Tests: native mode ──────────────────────────────────────────────


class TestFormatSearchResultsNativeMode:
    """Verify format_search_results in native tool mode."""

    def test_includes_native_tool_name(self):
        """Native mode should include [tool: SkillClass__method] tags."""
        output = format_search_results(_make_results(), tool_mode="native")
        assert "[tool: WeatherSkill__get_current_weather]" in output
        assert "[tool: CalcSkill__add]" in output

    def test_still_contains_dotted_path(self):
        """The original dotted path should still be present."""
        output = format_search_results(_make_results(), tool_mode="native")
        assert "WeatherSkill.get_current_weather" in output

    def test_empty_results_native(self):
        """Empty results in native mode should still say 'no results'."""
        output = format_search_results([], tool_mode="native")
        assert "No results found" in output

    def test_device_info_preserved(self):
        """Device info should still appear alongside native tool names."""
        results = [
            {
                "path": "WeatherSkill.get_current_weather",
                "signature": "get_current_weather(location: str) -> str",
                "summary": "Weather lookup.",
                "devices": ["living_room_pc", "office_pc"],
            },
        ]
        output = format_search_results(results, tool_mode="native")
        assert "[tool: WeatherSkill__get_current_weather]" in output
        assert "living_room_pc" in output
