"""Tests for the agent-mode skill tester (JSON-line protocol)."""

import json
from pathlib import Path

import pytest

from strawberry.testing.skill_tester_agent import (
    SkillTesterAgent,
    _err,
    _HistoryEntry,
    _load_tool_schemas,
    _ok,
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
        "class CalcSkill:\n"
        '    """A simple calculator."""\n'
        "\n"
        "    def add(self, a: int, b: int) -> int:\n"
        '        """Add two numbers."""\n'
        "        return a + b\n"
        "\n"
        "    def multiply(self, a: int, b: int) -> int:\n"
        '        """Multiply two numbers."""\n'
        "        return a * b\n",
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
def agent(tmp_skills_dir, tmp_config_dir):
    """Create a loaded SkillTesterAgent with temp skills and config."""
    a = SkillTesterAgent(skills_dir=tmp_skills_dir, config_dir=tmp_config_dir)
    a._ensure_loaded()
    return a


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


class TestResponseHelpers:
    """Test _ok and _err helper functions."""

    def test_ok_response(self):
        resp = _ok("test_type", {"key": "value"})
        assert resp["status"] == "ok"
        assert resp["type"] == "test_type"
        assert resp["data"] == {"key": "value"}

    def test_err_response(self):
        resp = _err("something went wrong")
        assert resp["status"] == "error"
        assert resp["message"] == "something went wrong"


# ---------------------------------------------------------------------------
# History entry serialization
# ---------------------------------------------------------------------------


class TestHistoryEntry:
    """Test _HistoryEntry serialization round-trip."""

    def test_to_dict(self):
        entry = _HistoryEntry(
            "search_skills", {"query": "calc"}, {"result": "..."}, 42.567
        )
        d = entry.to_dict()
        assert d["tool_name"] == "search_skills"
        assert d["arguments"] == {"query": "calc"}
        assert d["result"] == {"result": "..."}
        assert d["elapsed_ms"] == 42.57  # rounded to 2 decimals

    def test_round_trip(self):
        original = _HistoryEntry("python_exec", {"code": "1+1"}, {"result": "2"}, 10.0)
        restored = _HistoryEntry.from_dict(original.to_dict())
        assert restored.tool_name == original.tool_name
        assert restored.arguments == original.arguments
        assert restored.result == original.result
        assert restored.elapsed_ms == original.elapsed_ms


# ---------------------------------------------------------------------------
# Tool schema loading
# ---------------------------------------------------------------------------


class TestToolSchemaLoading:
    """Test tool schema loading from config directory."""

    def test_load_schemas(self, tmp_config_dir):
        schemas = _load_tool_schemas(tmp_config_dir)
        assert "search_skills" in schemas
        assert "python_exec" in schemas

    def test_load_schemas_strips_dollar_keys(self, tmp_config_dir):
        """$schema keys should be removed."""
        # Add a schema with $schema key
        tools_dir = tmp_config_dir / "tools"
        (tools_dir / "test_tool.json").write_text(
            json.dumps({"$schema": "http://json-schema.org/draft-07", "type": "object"}),
            encoding="utf-8",
        )
        schemas = _load_tool_schemas(tmp_config_dir)
        assert "$schema" not in schemas.get("test_tool", {})

    def test_load_schemas_missing_dir(self, tmp_path):
        schemas = _load_tool_schemas(tmp_path / "nonexistent")
        assert schemas == {}


# ---------------------------------------------------------------------------
# Command dispatch — get_system_prompt
# ---------------------------------------------------------------------------


class TestGetSystemPrompt:
    """Test the get_system_prompt command."""

    def test_returns_prompt(self, agent):
        resp = agent.dispatch({"command": "get_system_prompt"})
        assert resp["status"] == "ok"
        assert resp["type"] == "system_prompt"
        assert isinstance(resp["data"], str)
        assert len(resp["data"]) > 0

    def test_not_loaded(self, tmp_skills_dir, tmp_config_dir):
        a = SkillTesterAgent(skills_dir=tmp_skills_dir, config_dir=tmp_config_dir)
        resp = a.dispatch({"command": "get_system_prompt"})
        assert resp["status"] == "error"


# ---------------------------------------------------------------------------
# Command dispatch — get_tool_schemas
# ---------------------------------------------------------------------------


class TestGetToolSchemas:
    """Test the get_tool_schemas command."""

    def test_returns_schemas(self, agent):
        resp = agent.dispatch({"command": "get_tool_schemas"})
        assert resp["status"] == "ok"
        assert resp["type"] == "tool_schemas"
        assert "search_skills" in resp["data"]
        assert "python_exec" in resp["data"]


# ---------------------------------------------------------------------------
# Command dispatch — get_skills
# ---------------------------------------------------------------------------


class TestGetSkills:
    """Test the get_skills command."""

    def test_returns_skills(self, agent):
        resp = agent.dispatch({"command": "get_skills"})
        assert resp["status"] == "ok"
        assert resp["type"] == "skills"
        skills = resp["data"]
        assert len(skills) >= 1
        # Find our CalcSkill
        calc = next((s for s in skills if s["name"] == "CalcSkill"), None)
        assert calc is not None
        method_names = [m["name"] for m in calc["methods"]]
        assert "add" in method_names
        assert "multiply" in method_names

    def test_not_loaded(self, tmp_skills_dir, tmp_config_dir):
        a = SkillTesterAgent(skills_dir=tmp_skills_dir, config_dir=tmp_config_dir)
        resp = a.dispatch({"command": "get_skills"})
        assert resp["status"] == "error"


# ---------------------------------------------------------------------------
# Command dispatch — tool_call
# ---------------------------------------------------------------------------


class TestToolCall:
    """Test tool_call command with the three built-in tools."""

    def test_search_skills_empty(self, agent):
        resp = agent.dispatch({
            "command": "tool_call",
            "tool": "search_skills",
            "arguments": {"query": ""},
        })
        assert resp["status"] == "ok"
        assert resp["type"] == "tool_result"
        assert resp["data"]["tool"] == "search_skills"
        assert "result" in resp["data"]

    def test_search_skills_with_query(self, agent):
        resp = agent.dispatch({
            "command": "tool_call",
            "tool": "search_skills",
            "arguments": {"query": "add"},
        })
        assert resp["status"] == "ok"
        assert "add" in resp["data"].get("result", "").lower()

    def test_describe_function(self, agent):
        resp = agent.dispatch({
            "command": "tool_call",
            "tool": "describe_function",
            "arguments": {"path": "CalcSkill.add"},
        })
        assert resp["status"] == "ok"
        assert "result" in resp["data"]
        # Should contain the signature
        assert "add" in resp["data"]["result"]

    def test_python_exec(self, agent):
        resp = agent.dispatch({
            "command": "tool_call",
            "tool": "python_exec",
            "arguments": {"code": "print(device.CalcSkill.add(a=2, b=3))"},
        })
        assert resp["status"] == "ok"
        assert "5" in resp["data"].get("result", "")

    def test_python_exec_error(self, agent):
        resp = agent.dispatch({
            "command": "tool_call",
            "tool": "python_exec",
            "arguments": {"code": "raise ValueError('boom')"},
        })
        assert resp["status"] == "ok"
        assert "error" in resp["data"]
        assert "boom" in resp["data"]["error"]

    def test_unknown_tool(self, agent):
        resp = agent.dispatch({
            "command": "tool_call",
            "tool": "nonexistent_tool",
            "arguments": {},
        })
        assert resp["status"] == "ok"
        assert "error" in resp["data"]

    def test_missing_tool_field(self, agent):
        resp = agent.dispatch({"command": "tool_call", "arguments": {}})
        assert resp["status"] == "error"
        assert "Missing" in resp["message"]

    def test_tool_call_recorded_in_history(self, agent):
        agent.dispatch({
            "command": "tool_call",
            "tool": "search_skills",
            "arguments": {"query": "calc"},
        })
        resp = agent.dispatch({"command": "get_history"})
        assert len(resp["data"]) == 1
        assert resp["data"][0]["tool_name"] == "search_skills"

    def test_elapsed_ms_present(self, agent):
        resp = agent.dispatch({
            "command": "tool_call",
            "tool": "search_skills",
            "arguments": {"query": ""},
        })
        assert "elapsed_ms" in resp["data"]
        assert resp["data"]["elapsed_ms"] >= 0


# ---------------------------------------------------------------------------
# Command dispatch — history management
# ---------------------------------------------------------------------------


class TestHistory:
    """Test get_history and clear_history commands."""

    def test_empty_history(self, agent):
        resp = agent.dispatch({"command": "get_history"})
        assert resp["status"] == "ok"
        assert resp["data"] == []

    def test_history_accumulates(self, agent):
        for query in ["calc", "add", "multiply"]:
            agent.dispatch({
                "command": "tool_call",
                "tool": "search_skills",
                "arguments": {"query": query},
            })
        resp = agent.dispatch({"command": "get_history"})
        assert len(resp["data"]) == 3

    def test_clear_history(self, agent):
        agent.dispatch({
            "command": "tool_call",
            "tool": "search_skills",
            "arguments": {"query": "x"},
        })
        resp = agent.dispatch({"command": "clear_history"})
        assert resp["status"] == "ok"
        assert resp["data"]["cleared"] == 1

        resp = agent.dispatch({"command": "get_history"})
        assert resp["data"] == []


# ---------------------------------------------------------------------------
# Command dispatch — session save/load
# ---------------------------------------------------------------------------


class TestSessionPersistence:
    """Test session save and load for conversation continuity."""

    def test_save_and_load(self, agent, tmp_path):
        # Build some history
        agent.dispatch({
            "command": "tool_call",
            "tool": "search_skills",
            "arguments": {"query": "calc"},
        })
        agent.dispatch({
            "command": "tool_call",
            "tool": "python_exec",
            "arguments": {"code": "print(device.CalcSkill.add(a=1, b=2))"},
        })

        # Save session
        session_file = str(tmp_path / "session.json")
        resp = agent.dispatch({"command": "save_session", "path": session_file})
        assert resp["status"] == "ok"
        assert resp["data"]["entries"] == 2

        # Verify the file is valid JSON
        with open(session_file) as f:
            data = json.load(f)
        assert data["version"] == 1
        assert len(data["history"]) == 2

        # Load into a fresh agent
        agent2 = SkillTesterAgent(
            skills_dir=agent._skills_dir,
            config_dir=agent._config_dir,
        )
        agent2._ensure_loaded()
        resp = agent2.dispatch({"command": "load_session", "path": session_file})
        assert resp["status"] == "ok"
        assert resp["data"]["entries"] == 2

        # Verify history was restored
        resp = agent2.dispatch({"command": "get_history"})
        assert len(resp["data"]) == 2
        assert resp["data"][0]["tool_name"] == "search_skills"
        assert resp["data"][1]["tool_name"] == "python_exec"

    def test_save_missing_path(self, agent):
        resp = agent.dispatch({"command": "save_session"})
        assert resp["status"] == "error"

    def test_load_missing_path(self, agent):
        resp = agent.dispatch({"command": "load_session"})
        assert resp["status"] == "error"

    def test_load_nonexistent_file(self, agent):
        resp = agent.dispatch(
            {"command": "load_session", "path": "/nonexistent/file.json"}
        )
        assert resp["status"] == "error"

    def test_auto_load_session(self, tmp_skills_dir, tmp_config_dir, tmp_path):
        """Test that --session auto-loads on startup."""
        # Create a session file manually
        session_file = tmp_path / "auto.json"
        session_file.write_text(json.dumps({
            "version": 1,
            "skills_dir": str(tmp_skills_dir),
            "history": [
                {
                    "tool_name": "search_skills",
                    "arguments": {"query": "test"},
                    "result": {"result": "mocked"},
                    "elapsed_ms": 5.0,
                }
            ],
        }))

        agent = SkillTesterAgent(
            skills_dir=tmp_skills_dir,
            config_dir=tmp_config_dir,
            session_path=session_file,
        )
        agent._ensure_loaded()

        resp = agent.dispatch({"command": "get_history"})
        assert len(resp["data"]) == 1
        assert resp["data"][0]["tool_name"] == "search_skills"

    def test_continue_conversation(self, agent, tmp_path):
        """Test the full continue-a-conversation flow.

        1. Make some tool calls
        2. Save session
        3. Load session in a new agent
        4. Make more tool calls
        5. Verify the full history is continuous
        """
        # Original conversation
        agent.dispatch({
            "command": "tool_call",
            "tool": "search_skills",
            "arguments": {"query": ""},
        })
        agent.dispatch({
            "command": "tool_call",
            "tool": "describe_function",
            "arguments": {"path": "CalcSkill.add"},
        })

        # Save
        session_file = str(tmp_path / "continue.json")
        agent.dispatch({"command": "save_session", "path": session_file})

        # New agent resumes
        agent2 = SkillTesterAgent(
            skills_dir=agent._skills_dir,
            config_dir=agent._config_dir,
            session_path=Path(session_file),
        )
        agent2._ensure_loaded()

        # Continue the conversation
        agent2.dispatch({
            "command": "tool_call",
            "tool": "python_exec",
            "arguments": {"code": "print(device.CalcSkill.add(a=10, b=20))"},
        })

        # Full history should have 3 entries
        resp = agent2.dispatch({"command": "get_history"})
        assert len(resp["data"]) == 3
        assert resp["data"][0]["tool_name"] == "search_skills"
        assert resp["data"][1]["tool_name"] == "describe_function"
        assert resp["data"][2]["tool_name"] == "python_exec"


# ---------------------------------------------------------------------------
# Command dispatch — reload
# ---------------------------------------------------------------------------


class TestReload:
    """Test the reload command."""

    def test_reload(self, agent):
        resp = agent.dispatch({"command": "reload"})
        assert resp["status"] == "ok"
        assert resp["data"]["skills_count"] >= 1

    def test_reload_not_loaded(self, tmp_skills_dir, tmp_config_dir):
        a = SkillTesterAgent(skills_dir=tmp_skills_dir, config_dir=tmp_config_dir)
        resp = a.dispatch({"command": "reload"})
        assert resp["status"] == "error"


# ---------------------------------------------------------------------------
# Command dispatch — shutdown and errors
# ---------------------------------------------------------------------------


class TestShutdownAndErrors:
    """Test shutdown and error handling."""

    def test_shutdown(self, agent):
        resp = agent.dispatch({"command": "shutdown"})
        assert resp["status"] == "ok"
        assert resp["type"] == "shutdown"

    def test_unknown_command(self, agent):
        resp = agent.dispatch({"command": "nonexistent"})
        assert resp["status"] == "error"
        assert "Unknown command" in resp["message"]

    def test_empty_command(self, agent):
        resp = agent.dispatch({})
        assert resp["status"] == "error"

    def test_response_is_json_serializable(self, agent):
        """Every response must be JSON-serializable (no special types)."""
        for cmd in [
            {"command": "get_system_prompt"},
            {"command": "get_tool_schemas"},
            {"command": "get_skills"},
            {"command": "tool_call", "tool": "search_skills", "arguments": {"query": ""}},
            {"command": "get_history"},
            {"command": "shutdown"},
        ]:
            resp = agent.dispatch(cmd)
            # This should not raise
            serialized = json.dumps(resp)
            # And it should round-trip
            assert json.loads(serialized) == resp
