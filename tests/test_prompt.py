"""Tests for modular prompt generation.

Covers:
- PythonExecToolMode produces correct output per skill mode
- ToolModeProvider factory and registry
- build_example_call via provider (backward compat)
- Custom templates always include tools section
- Mode switch and tool mode switch messages
"""

from __future__ import annotations

from typing import List, Optional

import pytest

from strawberry.skills.loader import SkillMethod, SkillParam
from strawberry.skills.prompt import (
    PythonExecToolMode,
    ToolModeProvider,
    _placeholder_for_type,
    _strip_tool_sections,
    build_example_call,
    build_mode_switch_message,
    build_system_prompt,
    build_tool_mode_switch_message,
    build_tools_section,
    get_tool_mode_provider,
)
from strawberry.skills.sandbox.proxy_gen import SkillMode

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_method(
    name: str = "do_thing",
    signature: str = "do_thing()",
    params: Optional[List[SkillParam]] = None,
) -> SkillMethod:
    """Build a minimal SkillMethod for testing."""
    return SkillMethod(
        name=name,
        signature=signature,
        docstring=None,
        callable=lambda: None,
        params=params or [],
    )


# ---------------------------------------------------------------------------
# ToolModeProvider registry tests
# ---------------------------------------------------------------------------


class TestProviderRegistry:
    """Tests for get_tool_mode_provider and the registry."""

    def test_default_is_python_exec(self) -> None:
        """Default provider is PythonExecToolMode."""
        provider = get_tool_mode_provider()
        assert isinstance(provider, PythonExecToolMode)

    def test_explicit_python_exec(self) -> None:
        """Explicitly requesting python_exec returns PythonExecToolMode."""
        provider = get_tool_mode_provider("python_exec")
        assert isinstance(provider, PythonExecToolMode)

    def test_unknown_mode_raises(self) -> None:
        """Unknown tool mode raises ValueError."""
        with pytest.raises(ValueError, match="Unknown tool mode"):
            get_tool_mode_provider("nonexistent_mode")

    def test_provider_is_singleton(self) -> None:
        """Same provider instance is returned on repeated calls."""
        a = get_tool_mode_provider("python_exec")
        b = get_tool_mode_provider("python_exec")
        assert a is b

    def test_provider_is_subclass(self) -> None:
        """PythonExecToolMode is a proper ToolModeProvider subclass."""
        assert issubclass(PythonExecToolMode, ToolModeProvider)


# ---------------------------------------------------------------------------
# PythonExecToolMode section tests
# ---------------------------------------------------------------------------


class TestPythonExecToolMode:
    """Tests for the PythonExecToolMode provider."""

    @pytest.fixture
    def provider(self) -> PythonExecToolMode:
        return PythonExecToolMode()

    def test_tool_header_mentions_three_tools(self, provider) -> None:
        """Header lists exactly 3 tools."""
        header = provider.tool_header()
        assert "search_skills" in header
        assert "describe_function" in header
        assert "python_exec" in header

    def test_local_discovery_has_example(self, provider) -> None:
        """Local discovery section includes usage example."""
        section = provider.discovery_section(SkillMode.LOCAL)
        assert 'search_skills(query="weather")' in section

    def test_remote_discovery_same_as_local(self, provider) -> None:
        """Discovery section is mode-agnostic."""
        local = provider.discovery_section(SkillMode.LOCAL)
        remote = provider.discovery_section(SkillMode.REMOTE)
        assert local == remote  # simplified: no mode-specific variants

    def test_local_execution_uses_device(self, provider) -> None:
        """Local exec section uses device.* syntax."""
        section = provider.execution_section(SkillMode.LOCAL)
        assert "device.<Skill>" in section

    def test_remote_execution_uses_devices(self, provider) -> None:
        """Remote exec section uses devices.* syntax."""
        section = provider.execution_section(SkillMode.REMOTE)
        assert "devices.<device>.<Skill>" in section

    def test_local_examples_have_device_syntax(self, provider) -> None:
        """Local examples use device.* syntax."""
        examples = provider.examples_section(SkillMode.LOCAL)
        assert "device.WeatherSkill" in examples

    def test_remote_examples_have_devices_syntax(self, provider) -> None:
        """Remote examples use devices.* syntax."""
        examples = provider.examples_section(SkillMode.REMOTE)
        assert "devices.my_device" in examples

    def test_rules_mention_print(self, provider) -> None:
        """Rules mention print() requirement."""
        rules = provider.rules_section()
        assert "print()" in rules


# ---------------------------------------------------------------------------
# build_example_call tests (backward-compatible wrapper)
# ---------------------------------------------------------------------------


class TestBuildExampleCall:
    """Tests for build_example_call using structured params."""

    def test_no_params(self) -> None:
        method = _make_method("ping", "ping()")
        result = build_example_call("DemoSkill", method)
        assert result == "print(device.DemoSkill.ping())"

    def test_required_params_with_type_hints(self) -> None:
        method = _make_method(
            "add",
            "add(a: int, b: int) -> int",
            params=[
                SkillParam(name="a", type_hint="int"),
                SkillParam(name="b", type_hint="int"),
            ],
        )
        result = build_example_call("CalcSkill", method)
        assert result == "print(device.CalcSkill.add(a=0, b=0))"

    def test_string_param_placeholder(self) -> None:
        method = _make_method(
            "greet",
            "greet(name: str) -> str",
            params=[SkillParam(name="name", type_hint="str")],
        )
        result = build_example_call("HelloSkill", method)
        assert result == "print(device.HelloSkill.greet(name='...'))"

    def test_param_with_default_uses_actual_default(self) -> None:
        method = _make_method(
            "set_volume",
            "set_volume(level: int = 50)",
            params=[SkillParam(name="level", type_hint="int", default="50")],
        )
        result = build_example_call("AudioSkill", method)
        assert result == "print(device.AudioSkill.set_volume(level=50))"

    def test_none_default_substituted_with_placeholder(self) -> None:
        method = _make_method(
            "search",
            "search(query: str, limit: int = None)",
            params=[
                SkillParam(name="query", type_hint="str"),
                SkillParam(name="limit", type_hint="int", default="None"),
            ],
        )
        result = build_example_call("SearchSkill", method)
        assert result == "print(device.SearchSkill.search(query='...', limit=0))"

    def test_complex_default_preserved(self) -> None:
        """Key regression test — commas in defaults don't break parsing."""
        method = _make_method(
            "send",
            "send(data: dict = {'a': 1, 'b': 2})",
            params=[
                SkillParam(
                    name="data",
                    type_hint="dict",
                    default="{'a': 1, 'b': 2}",
                ),
            ],
        )
        result = build_example_call("ApiSkill", method)
        assert "data={'a': 1, 'b': 2}" in result

    def test_list_and_dict_placeholders(self) -> None:
        method = _make_method(
            "batch",
            "batch(items: list, config: dict)",
            params=[
                SkillParam(name="items", type_hint="list"),
                SkillParam(name="config", type_hint="dict"),
            ],
        )
        result = build_example_call("BatchSkill", method)
        assert result == "print(device.BatchSkill.batch(items=[], config={}))"


# ---------------------------------------------------------------------------
# _placeholder_for_type tests
# ---------------------------------------------------------------------------


class TestPlaceholderForType:
    """Tests for the type-hint placeholder helper."""

    def test_empty_hint(self) -> None:
        assert _placeholder_for_type("") == "..."

    def test_str_hint(self) -> None:
        assert _placeholder_for_type("str") == "'...'"

    def test_optional_str_hint(self) -> None:
        assert _placeholder_for_type("optional[str]") == "'...'"

    def test_int_hint(self) -> None:
        assert _placeholder_for_type("int") == "0"

    def test_float_hint(self) -> None:
        assert _placeholder_for_type("float") == "0.0"

    def test_bool_hint(self) -> None:
        assert _placeholder_for_type("bool") == "True"

    def test_list_hint(self) -> None:
        assert _placeholder_for_type("list") == "[]"

    def test_dict_hint(self) -> None:
        assert _placeholder_for_type("dict") == "{}"


# ---------------------------------------------------------------------------
# Custom template tests
# ---------------------------------------------------------------------------


class TestCustomTemplateIncludesToolsSection:
    """Ensure custom templates always include the tools section."""

    def test_custom_template_with_placeholder(self) -> None:
        template = "You are a custom bot.\n{skill_descriptions}"
        result = build_system_prompt(
            skills=[],
            mode=SkillMode.LOCAL,
            device_name="test_device",
            custom_template=template,
        )
        assert "You are a custom bot" in result
        assert "python_exec" in result
        assert "search_skills" in result

    def test_custom_template_without_placeholder(self) -> None:
        template = "You are a pirate assistant. Arr!"
        result = build_system_prompt(
            skills=[],
            mode=SkillMode.LOCAL,
            device_name="test_device",
            custom_template=template,
        )
        assert "You are a pirate assistant" in result
        assert "python_exec" in result

    def test_default_prompt_has_tools_section(self) -> None:
        result = build_system_prompt(
            skills=[],
            mode=SkillMode.LOCAL,
            device_name="test_device",
        )
        assert "Strawberry" in result
        assert "python_exec" in result
        assert "search_skills" in result


# ---------------------------------------------------------------------------
# build_tools_section composition tests
# ---------------------------------------------------------------------------


class TestBuildToolsSection:
    """Tests for the composed tools section."""

    def test_local_has_device_syntax(self) -> None:
        result = build_tools_section(SkillMode.LOCAL, [])
        assert "device.<Skill>" in result

    def test_remote_has_devices_syntax(self) -> None:
        result = build_tools_section(SkillMode.REMOTE, [])
        assert "devices.<device>" in result

    def test_accepts_tool_mode_kwarg(self) -> None:
        """Verify tool_mode parameter is accepted."""
        result = build_tools_section(
            SkillMode.LOCAL,
            [],
            tool_mode="python_exec",
        )
        assert "python_exec" in result


# ---------------------------------------------------------------------------
# Mode switch message tests
# ---------------------------------------------------------------------------


class TestModeSwitchMessages:
    """Tests for mode switch and tool mode switch messages."""

    def test_switch_to_online(self) -> None:
        msg = build_mode_switch_message("online")
        assert "ONLINE mode" in msg
        assert "devices.<device>" in msg

    def test_switch_to_local(self) -> None:
        msg = build_mode_switch_message("local")
        assert "LOCAL mode" in msg
        assert "device.<Skill>" in msg

    def test_tool_mode_switch(self) -> None:
        msg = build_tool_mode_switch_message(
            SkillMode.LOCAL,
            "python_exec",
        )
        assert "Tool mode changed" in msg
        assert "python_exec" in msg
        assert "device.<Skill>" in msg


# ---------------------------------------------------------------------------
# _strip_tool_sections tests
# ---------------------------------------------------------------------------


class TestStripToolSections:
    """Tests for stripping legacy tool sections from custom templates."""

    def test_strips_available_tools(self) -> None:
        text = "Role intro.\n\n## Available Tools\n\nTool list here.\n"
        result = _strip_tool_sections(text)
        assert "Role intro." in result
        assert "Available Tools" not in result
        assert "Tool list here" not in result

    def test_strips_python_exec(self) -> None:
        text = "Custom role.\n\n## python_exec\n\nUse python_exec...\n"
        result = _strip_tool_sections(text)
        assert "Custom role." in result
        assert "python_exec" not in result

    def test_preserves_non_tool_headings(self) -> None:
        text = (
            "Role text.\n\n## My Custom Section\n\nKeep this.\n"
            "## python_exec\n\nStrip this.\n"
        )
        result = _strip_tool_sections(text)
        assert "My Custom Section" in result
        assert "Keep this" in result
        assert "python_exec" not in result

    def test_strips_all_known_headers(self) -> None:
        """All known tool headers are stripped."""
        sections = [
            "## Available Tools",
            "## search_skills",
            "## describe_function",
            "## python_exec",
            "## Examples",
            "## Rules",
            "## Searching Tips",
            "## Critical Notes",
        ]
        text = "Personality.\n\n" + "\n\nContent.\n\n".join(sections)
        result = _strip_tool_sections(text)
        assert "Personality." in result
        for header in sections:
            assert header not in result

    def test_legacy_template_no_duplication(self) -> None:
        """Full old-style prompt used as custom_template produces
        only ONE tools section (no duplication)."""
        legacy = (
            "You are Strawberry.\n\n"
            "## Available Tools\n\n"
            "1) search_skills 2) describe_function 3) python_exec\n\n"
            "## python_exec\n\n"
            "Use python_exec to call skills.\n\n"
            "## Rules\n\n"
            "1. Don't call directly.\n"
        )
        result = build_system_prompt(
            skills=[],
            mode=SkillMode.LOCAL,
            device_name="test",
            custom_template=legacy,
        )
        # Count occurrences of "## Available Tools"
        count = result.count("## Available Tools")
        assert count == 1, f"Expected 1 '## Available Tools', got {count}"
