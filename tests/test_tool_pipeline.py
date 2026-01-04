"""Tests for the tool-call pipeline (search_skills/describe_function/python_exec).

These tests avoid the Deno/Pyodide sandbox and instead validate the core parsing/execution
path in `SkillService`, using a temporary skills directory.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from strawberry.skills.service import SkillService


@pytest.fixture()
def temp_skills_dir(tmp_path: Path) -> Path:
    """Create a temporary skills directory with one simple skill."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    (skills_dir / "weather_skill.py").write_text(
        textwrap.dedent(
            """
            class WeatherSkill:
                \"\"\"Weather utilities.\"\"\"

                def get_current_weather(self, location: str = \"here\") -> str:
                    \"\"\"Return the weather for a location.\"\"\"
                    return f\"sunny in {location}\"
            """
        ).lstrip(),
        encoding="utf-8",
    )

    return skills_dir


@pytest.fixture()
def skill_service(temp_skills_dir: Path) -> SkillService:
    """SkillService wired to the temporary skills directory."""
    service = SkillService(skills_path=temp_skills_dir, use_sandbox=False)
    service.load_skills()
    return service


@pytest.mark.asyncio
async def test_search_skills_tool_returns_skill_paths(skill_service: SkillService) -> None:
    """`search_skills` should return JSON describing available skills."""
    result = await skill_service.execute_tool_async("search_skills", {"query": "weather"})
    assert "result" in result
    payload = result["result"]
    assert "WeatherSkill.get_current_weather" in payload


@pytest.mark.asyncio
async def test_describe_function_tool_returns_signature(skill_service: SkillService) -> None:
    """`describe_function` should return a full signature + docstring."""
    result = await skill_service.execute_tool_async(
        "describe_function",
        {"path": "WeatherSkill.get_current_weather"},
    )
    assert "result" in result
    text = result["result"]
    assert "def get_current_weather" in text
    assert "Return the weather for a location" in text


@pytest.mark.asyncio
async def test_python_exec_tool_can_call_skill(skill_service: SkillService) -> None:
    """`python_exec` should be able to call a skill via `device.<Skill>.<method>()`."""
    result = await skill_service.execute_tool_async(
        "python_exec",
        {"code": "print(device.WeatherSkill.get_current_weather('Seattle'))"},
    )
    assert result == {"result": "sunny in Seattle"}


@pytest.mark.asyncio
async def test_unknown_tool_returns_error(skill_service: SkillService) -> None:
    """Unknown tool names should return a structured error."""
    result = await skill_service.execute_tool_async("not_a_tool", {})
    assert "error" in result
    assert "Unknown tool" in result["error"]
