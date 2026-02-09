"""Tests for the interactive skill tester CLI tool."""

import json

import pytest

from strawberry.testing.skill_tester import (
    SkillTester,
    _HistoryEntry,
    _load_tool_schemas,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_skills_dir(tmp_path):
    """Create a temporary skills directory with a simple test skill."""
    skill_repo = tmp_path / "skills" / "calc_skill"
    skill_repo.mkdir(parents=True)

    (skill_repo / "skill.py").write_text(
        'class CalcSkill:\n'
        '    """A simple calculator."""\n'
        '\n'
        '    def add(self, a: int, b: int) -> int:\n'
        '        """Add two numbers."""\n'
        '        return a + b\n'
        '\n'
        '    def multiply(self, a: int, b: int) -> int:\n'
        '        """Multiply two numbers."""\n'
        '        return a * b\n',
        encoding="utf-8",
    )
    return tmp_path / "skills"


@pytest.fixture
def tmp_config_dir(tmp_path):
    """Create a temporary config directory with tool schemas."""
    tools_dir = tmp_path / "config" / "tools"
    tools_dir.mkdir(parents=True)

    (tools_dir / "search_skills.json").write_text(
        json.dumps({
            "type": "object",
            "description": "Search for skills.",
            "properties": {
                "query": {"type": "string", "default": ""},
            },
        }),
        encoding="utf-8",
    )
    (tools_dir / "python_exec.json").write_text(
        json.dumps({
            "type": "object",
            "description": "Execute Python code.",
            "properties": {
                "code": {"type": "string"},
            },
        }),
        encoding="utf-8",
    )
    return tmp_path / "config"


@pytest.fixture
def tester(tmp_skills_dir, tmp_config_dir):
    """Create a SkillTester with temp skills and config."""
    t = SkillTester(skills_dir=tmp_skills_dir, config_dir=tmp_config_dir)
    t._load()
    return t


# ---------------------------------------------------------------------------
# Tests: Tool schema loading
# ---------------------------------------------------------------------------


class TestToolSchemaLoading:
    """Tests for _load_tool_schemas."""

    def test_loads_json_schemas(self, tmp_config_dir):
        """Tool schemas are loaded from config/tools/*.json."""
        schemas = _load_tool_schemas(tmp_config_dir)
        assert "search_skills" in schemas
        assert "python_exec" in schemas

    def test_missing_dir_returns_empty(self, tmp_path):
        """Returns empty dict when tools dir doesn't exist."""
        schemas = _load_tool_schemas(tmp_path / "nonexistent")
        assert schemas == {}


# ---------------------------------------------------------------------------
# Tests: Skill loading
# ---------------------------------------------------------------------------


class TestSkillLoading:
    """Tests for skill loading in the tester."""

    def test_loads_skills(self, tester):
        """Skills are loaded from the skills directory."""
        assert tester._service is not None
        skills = tester._service.get_all_skills()
        assert len(skills) == 1
        assert skills[0].name == "CalcSkill"

    def test_reload_skills(self, tester):
        """Reload picks up skills again."""
        tester._reload()
        skills = tester._service.get_all_skills()
        assert len(skills) == 1


# ---------------------------------------------------------------------------
# Tests: Tool execution
# ---------------------------------------------------------------------------


class TestToolExecution:
    """Tests for executing tools through the tester."""

    def test_search_skills_empty_query(self, tester):
        """search_skills with empty query returns all skills."""
        result = tester._execute_tool("search_skills", {"query": ""})
        assert "result" in result
        # Result is a text listing from _execute_search_skills
        assert "CalcSkill.add" in result["result"]
        assert "CalcSkill.multiply" in result["result"]

    def test_search_skills_with_query(self, tester):
        """search_skills filters by query."""
        result = tester._execute_tool(
            "search_skills", {"query": "multiply"}
        )
        assert "result" in result
        assert "CalcSkill.multiply" in result["result"]

    def test_describe_function(self, tester):
        """describe_function returns signature and docstring."""
        result = tester._execute_tool(
            "describe_function", {"path": "CalcSkill.add"}
        )
        assert "result" in result
        assert "add" in result["result"]
        assert "Add two numbers" in result["result"]

    def test_describe_function_not_found(self, tester):
        """describe_function returns error for unknown path."""
        result = tester._execute_tool(
            "describe_function", {"path": "FakeSkill.nope"}
        )
        assert "result" in result
        # Should contain an error message about not found
        assert "not found" in result["result"].lower() or "error" in result["result"].lower()

    def test_python_exec(self, tester):
        """python_exec runs code and returns output."""
        result = tester._execute_tool(
            "python_exec",
            {"code": "print(device.CalcSkill.add(a=2, b=3))"},
        )
        assert "result" in result
        assert "5" in result["result"]

    def test_python_exec_error(self, tester):
        """python_exec returns error for bad code."""
        result = tester._execute_tool(
            "python_exec",
            {"code": "raise ValueError('boom')"},
        )
        assert "error" in result
        assert "boom" in result["error"]

    def test_unknown_tool(self, tester):
        """Unknown tool returns error."""
        result = tester._execute_tool("fake_tool", {})
        assert "error" in result
        assert "Unknown tool" in result["error"]

    def test_history_recorded(self, tester):
        """Tool calls are recorded in history."""
        tester._execute_tool("search_skills", {"query": ""})
        tester._execute_tool(
            "python_exec",
            {"code": "print(device.CalcSkill.add(a=1, b=2))"},
        )
        assert len(tester._history) == 2
        assert tester._history[0].tool_name == "search_skills"
        assert tester._history[1].tool_name == "python_exec"

    def test_history_has_timing(self, tester):
        """History entries have timing info."""
        tester._execute_tool("search_skills", {"query": ""})
        assert tester._history[0].elapsed_ms >= 0


# ---------------------------------------------------------------------------
# Tests: Input parsing
# ---------------------------------------------------------------------------


class TestInputParsing:
    """Tests for _parse_tool_call."""

    def test_search_skills_bare(self, tester):
        """'search_skills' parses to empty query."""
        result = tester._parse_tool_call("search_skills")
        assert result == ("search_skills", {"query": ""})

    def test_search_skills_with_query(self, tester):
        """'search_skills weather' parses correctly."""
        result = tester._parse_tool_call("search_skills weather")
        assert result == ("search_skills", {"query": "weather"})

    def test_search_skills_with_kwarg(self, tester):
        """'search_skills query=\"weather\"' parses correctly."""
        result = tester._parse_tool_call('search_skills query="weather"')
        assert result == ("search_skills", {"query": "weather"})

    def test_describe_function(self, tester):
        """'describe_function Skill.method' parses correctly."""
        result = tester._parse_tool_call(
            "describe_function CalcSkill.add"
        )
        assert result == ("describe_function", {"path": "CalcSkill.add"})

    def test_describe_function_empty_returns_none(self, tester):
        """'describe_function' with no path returns None."""
        result = tester._parse_tool_call("describe_function")
        assert result is None

    def test_python_exec_inline(self, tester):
        """'python_exec print(1+1)' parses correctly."""
        result = tester._parse_tool_call("python_exec print(1+1)")
        assert result == ("python_exec", {"code": "print(1+1)"})

    def test_python_exec_json_format(self, tester):
        """python_exec with JSON argument parses correctly."""
        result = tester._parse_tool_call(
            'python_exec {"code": "print(42)"}'
        )
        assert result == ("python_exec", {"code": "print(42)"})

    def test_empty_input_returns_none(self, tester):
        """Empty input returns None."""
        result = tester._parse_tool_call("")
        assert result is None

    def test_unrecognized_returns_none(self, tester):
        """Unrecognized input returns None."""
        result = tester._parse_tool_call("hello world")
        assert result is None


# ---------------------------------------------------------------------------
# Tests: History entry formatting
# ---------------------------------------------------------------------------


class TestHistoryEntry:
    """Tests for _HistoryEntry."""

    def test_format_short_success(self):
        """Successful entry formats with checkmark."""
        entry = _HistoryEntry(
            tool_name="search_skills",
            arguments={"query": "test"},
            result={"result": "found stuff"},
            elapsed_ms=42.5,
        )
        formatted = entry.format_short(1)
        assert "search_skills" in formatted
        assert "42ms" in formatted

    def test_format_short_error(self):
        """Failed entry formats with X mark."""
        entry = _HistoryEntry(
            tool_name="python_exec",
            arguments={"code": "bad"},
            result={"error": "SyntaxError"},
            elapsed_ms=10.0,
        )
        formatted = entry.format_short(2)
        assert "python_exec" in formatted
