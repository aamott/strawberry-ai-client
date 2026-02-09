"""Tests for the MCP skill repo: class_builder, naming, and loader integration."""

import inspect
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from skills.mcp_skill.class_builder import (
    _normalize_method_name,
    _server_name_to_class_name,
    build_all_skill_classes,
    build_skill_class,
)
from skills.mcp_skill.mcp_client import MCPServerInfo, MCPToolInfo

# ── Naming tests ────────────────────────────────────────────────────────────


class TestServerNameToClassName:
    """Tests for _server_name_to_class_name."""

    def test_space_separated(self) -> None:
        assert _server_name_to_class_name("Home Assistant") == "HomeAssistantSkill"

    def test_lowercase_single_word(self) -> None:
        assert _server_name_to_class_name("firebase") == "FirebaseSkill"

    def test_already_has_skill_suffix(self) -> None:
        # A server named "MySkill" should not get double-suffixed
        assert _server_name_to_class_name("MySkill") == "MySkill"

    def test_preserves_inner_casing(self) -> None:
        assert _server_name_to_class_name("GitHub") == "GitHubSkill"

    def test_alphanumeric(self) -> None:
        assert _server_name_to_class_name("context7") == "Context7Skill"

    def test_hyphenated(self) -> None:
        assert _server_name_to_class_name("my-custom-server") == "MyCustomServerSkill"

    def test_underscored(self) -> None:
        assert _server_name_to_class_name("my_custom_server") == "MyCustomServerSkill"

    def test_mixed_separators(self) -> None:
        assert _server_name_to_class_name("foo-bar_baz qux") == "FooBarBazQuxSkill"


class TestNormalizeMethodName:
    """Tests for _normalize_method_name."""

    def test_hyphen_replaced(self) -> None:
        assert _normalize_method_name("query-docs") == "query_docs"

    def test_multiple_hyphens(self) -> None:
        assert _normalize_method_name("resolve-library-id") == "resolve_library_id"

    def test_already_valid(self) -> None:
        assert _normalize_method_name("HassTurnOn") == "HassTurnOn"

    def test_underscore_preserved(self) -> None:
        assert _normalize_method_name("my_tool") == "my_tool"


# ── Class builder tests ─────────────────────────────────────────────────────


def _make_fake_call_tool() -> MagicMock:
    """Create a mock call_tool function that returns a canned response."""
    mock = MagicMock(return_value="tool result")
    return mock


def _make_server_info(
    name: str = "Test Server",
    tools: list | None = None,
) -> MCPServerInfo:
    """Build a test MCPServerInfo."""
    if tools is None:
        tools = [
            MCPToolInfo(
                name="do_thing",
                description="Does a thing.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "x": {"type": "string", "description": "The X value"},
                        "y": {"type": "integer", "description": "The Y value"},
                    },
                    "required": ["x"],
                },
            ),
            MCPToolInfo(
                name="other_action",
                description="Another action.",
                input_schema={},
            ),
        ]
    return MCPServerInfo(server_name=name, tools=tools, session=None)


class TestBuildSkillClass:
    """Tests for build_skill_class."""

    def test_creates_class_with_correct_name(self) -> None:
        info = _make_server_info("Home Assistant")
        cls = build_skill_class(info, _make_fake_call_tool())
        assert cls.__name__ == "HomeAssistantSkill"

    def test_class_has_methods_for_each_tool(self) -> None:
        info = _make_server_info()
        cls = build_skill_class(info, _make_fake_call_tool())
        assert hasattr(cls, "do_thing")
        assert hasattr(cls, "other_action")
        assert callable(cls.do_thing)

    def test_class_has_docstring(self) -> None:
        info = _make_server_info("firebase", tools=[
            MCPToolInfo(name="deploy", description="Deploy app.", input_schema={}),
        ])
        cls = build_skill_class(info, _make_fake_call_tool())
        assert "firebase" in cls.__doc__
        assert "1 tool" in cls.__doc__

    def test_method_has_docstring(self) -> None:
        info = _make_server_info()
        cls = build_skill_class(info, _make_fake_call_tool())
        assert "Does a thing" in cls.do_thing.__doc__
        assert "x:" in cls.do_thing.__doc__

    def test_caller_module_is_set(self) -> None:
        info = _make_server_info()
        cls = build_skill_class(info, _make_fake_call_tool(), caller_module="my.module")
        assert cls.__module__ == "my.module"

    def test_method_validates_required_params(self) -> None:
        info = _make_server_info()
        mock_fn = _make_fake_call_tool()
        cls = build_skill_class(info, mock_fn)
        instance = cls()
        # Missing required 'x'
        with pytest.raises(ValueError, match="Missing required argument 'x'"):
            instance.do_thing(y=42)

    def test_method_rejects_unknown_arguments(self) -> None:
        """Extra/unknown kwargs should raise ValueError, not be silently ignored."""
        info = _make_server_info()
        mock_fn = _make_fake_call_tool()
        cls = build_skill_class(info, mock_fn)
        instance = cls()
        # 'bogus' is not in the inputSchema properties
        with pytest.raises(ValueError, match="Unknown argument"):
            instance.do_thing(x="hello", bogus="oops")
        # Ensure the tool was NOT called
        mock_fn.assert_not_called()

    def test_method_has_proper_signature(self) -> None:
        """inspect.signature() should show real param names, not **kwargs."""
        info = _make_server_info()
        cls = build_skill_class(info, _make_fake_call_tool())
        sig = inspect.signature(cls.do_thing)
        param_names = list(sig.parameters.keys())
        # 'self' is first, then the schema params
        assert "self" in param_names
        assert "x" in param_names
        assert "y" in param_names
        # 'x' is required (no default), 'y' is optional (has default)
        assert sig.parameters["x"].default is inspect.Parameter.empty
        assert sig.parameters["y"].default is None

    def test_method_calls_tool_fn(self) -> None:
        """Method delegates to the call_tool_fn with correct args."""
        info = _make_server_info("srv", tools=[
            MCPToolInfo(
                name="ping",
                description="Ping.",
                input_schema={
                    "type": "object",
                    "properties": {"host": {"type": "string"}},
                    "required": ["host"],
                },
            ),
        ])
        mock_fn = _make_fake_call_tool()
        cls = build_skill_class(info, mock_fn)
        instance = cls()

        # The method should call call_tool_fn synchronously
        result = instance.ping(host="localhost")
        assert result == "tool result"
        mock_fn.assert_called_once_with("ping", {"host": "localhost"})


class TestBuildAllSkillClasses:
    """Tests for build_all_skill_classes."""

    def test_builds_multiple_classes(self) -> None:
        servers = [
            _make_server_info("Alpha"),
            _make_server_info("Beta"),
        ]
        fns = {
            "Alpha": _make_fake_call_tool(),
            "Beta": _make_fake_call_tool(),
        }
        classes = build_all_skill_classes(servers, fns)
        names = {c.__name__ for c in classes}
        assert names == {"AlphaSkill", "BetaSkill"}

    def test_skips_server_without_fn(self) -> None:
        servers = [_make_server_info("Alpha")]
        fns: Dict[str, Any] = {}  # No function provided
        classes = build_all_skill_classes(servers, fns)
        assert len(classes) == 0

    def test_caller_module_propagated(self) -> None:
        servers = [_make_server_info("Srv")]
        fns = {"Srv": _make_fake_call_tool()}
        classes = build_all_skill_classes(servers, fns, caller_module="test.mod")
        assert classes[0].__module__ == "test.mod"


# ── Loader integration tests ───────────────────────────────────────────────


class TestLoaderIntegrationWithDynamicClasses:
    """Test that the SkillLoader picks up dynamically-created *Skill classes."""

    def test_loader_finds_dynamic_skill_classes(self) -> None:
        """Simulate what mcp_skill/skill.py does: create classes dynamically
        and assign them to module globals, then verify the loader sees them."""
        from strawberry.skills.loader import SkillLoader

        with tempfile.TemporaryDirectory() as tmpdir:
            skills_dir = Path(tmpdir)
            repo_dir = skills_dir / "dynamic_repo"
            repo_dir.mkdir()

            # Entrypoint that dynamically creates a skill class
            (repo_dir / "skill.py").write_text(
                '''
class _Builder:
    """Helper to build dynamic classes."""
    @staticmethod
    def make():
        attrs = {
            "__doc__": "Dynamic skill.",
            "hello": lambda self: "hi",
        }
        return type("DynamicSkill", (), attrs)

# Create and assign to module scope
DynamicSkill = _Builder.make()
# Set __module__ to match what the loader expects
DynamicSkill.__module__ = __name__
'''.lstrip()
            )

            loader = SkillLoader(skills_dir)
            skills = loader.load_all()

            names = {s.name for s in skills}
            assert "DynamicSkill" in names, f"DynamicSkill not in {names}"

    def test_loader_finds_multiple_dynamic_classes(self) -> None:
        """Multiple dynamically-created classes in one entrypoint."""
        from strawberry.skills.loader import SkillLoader

        with tempfile.TemporaryDirectory() as tmpdir:
            skills_dir = Path(tmpdir)
            repo_dir = skills_dir / "multi_dynamic"
            repo_dir.mkdir()

            (repo_dir / "skill.py").write_text(
                '''
def _make_skill(name, method_name, return_val):
    def method(self):
        return return_val
    method.__name__ = method_name
    attrs = {
        "__doc__": f"Skill {name}",
        method_name: method,
    }
    cls = type(name, (), attrs)
    cls.__module__ = __name__
    return cls

AlphaSkill = _make_skill("AlphaSkill", "greet", "hello")
BetaSkill = _make_skill("BetaSkill", "farewell", "goodbye")
'''.lstrip()
            )

            loader = SkillLoader(skills_dir)
            skills = loader.load_all()

            names = {s.name for s in skills}
            assert "AlphaSkill" in names
            assert "BetaSkill" in names

            assert loader.call_method("AlphaSkill", "greet") == "hello"
            assert loader.call_method("BetaSkill", "farewell") == "goodbye"
