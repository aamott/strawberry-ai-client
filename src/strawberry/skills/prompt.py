"""Modular system prompt generation for the skill service.

Prompts are composed along two independent axes:

1. **Skill mode** (``SkillMode.LOCAL`` / ``SkillMode.REMOTE``) —
   controls the syntax for addressing skills (``device.*`` vs
   ``devices.<device>.*``).

2. **Tool mode** (``ToolModeProvider`` subclass) — controls *how* the LLM
   executes skills (``python_exec``, and in the future ``ts_exec`` or
   native tool calling).

Architecture::

    ROLE_SECTION (static, tool-agnostic)
      + ToolModeProvider.build_tools_section(skill_mode, skills)
      = full system prompt  -or-  mode-switch message

Composition points:

- **Chat start**: ROLE + provider.build_tools_section(skill_mode, skills)
- **Hub disconnect**: switch notice + provider.build_tools_section(LOCAL, skills)
- **Hub connect**: switch notice + provider.build_tools_section(REMOTE, skills)
- **Tool mode change**: switch notice + new_provider.build_tools_section(...)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from .loader import SkillInfo, SkillMethod
    from .sandbox.proxy_gen import SkillMode

logger = logging.getLogger(__name__)

# If total skill *functions* exceed this threshold, the system prompt
# omits the embedded skill catalog and relies entirely on search_skills
# for tool discovery (Claude tool-search style).
MAX_FUNCTIONS_FOR_EMBED = 30

# When we do embed, cap the number of skill *classes* shown.
MAX_SKILLS_IN_PROMPT = 8


# ---------------------------------------------------------------------------
# Role section (static, tool-agnostic)
# ---------------------------------------------------------------------------

ROLE_SECTION = """\
You are Strawberry, a helpful AI assistant with access to skills.

## Critical Notes

- Try to be helpful. If the user requests something that you suspect
  requires a skill (fetching weather, adding numbers, etc), call
  `search_skills` to find the skill. If you need more information
  about a skill function, call `describe_function`.
- Do NOT say "I can't" until you have searched for skills and
  confirmed that the skill does not exist. It may take multiple
  searches.
- After you find the right skill, execute it immediately. Don't ask
  for confirmation unless you actually need clarification (e.g., a
  required location you don't have).
- If a tool call fails, fix the error and retry immediately.
  Do NOT give up or ask the user for help after a single error.
- After tool calls complete, ALWAYS provide a final natural-language
  answer. Where useful, include interim responses ("Let me find that
  for you") to keep the user engaged.

## Searching Tips

search_skills matches against method names, skill names, and
descriptions. Search by **action** or **verb**, not by specific
entity/object names.
- To turn on a lamp, search 'turn on' or 'lamp'.
- To set brightness, search 'light' or 'brightness'.
- If a skill doesn't show up on the first try, continue searching
  and experiment with different keywords."""


# ---------------------------------------------------------------------------
# Skill catalog helpers (shared across tool modes)
# ---------------------------------------------------------------------------


def _count_total_functions(skills: List["SkillInfo"]) -> int:
    """Count total methods across all loaded skills."""
    return sum(len(s.methods) for s in skills)


def _build_local_skill_descriptions(skills: List["SkillInfo"]) -> str:
    """Build compact local skill descriptions for the system prompt.

    Only called when total functions <= MAX_FUNCTIONS_FOR_EMBED.
    Produces a concise catalog so the LLM knows what's available
    without needing to call search_skills first.

    Args:
        skills: Loaded local skills.

    Returns:
        Multiline section with header + bullet list, or empty string.
    """
    descriptions: list[str] = ["## Available Skills\n"]
    skills_for_prompt = skills[:MAX_SKILLS_IN_PROMPT]
    for skill in skills_for_prompt:
        class_summary = "No description available"
        if skill.class_obj.__doc__:
            class_summary = (
                skill.class_obj.__doc__.strip().split("\n")[0].strip()
            )

        method_count = len(skill.methods)
        method_word = "method" if method_count == 1 else "methods"

        sample_methods = ", ".join(m.name for m in skill.methods[:3])
        if method_count > 3:
            sample_methods += ", ..."

        descriptions.append(
            f"- {skill.name} ({method_count} {method_word})"
        )
        descriptions.append(f"  {class_summary}")
        if sample_methods:
            descriptions.append(f"  Sample methods: {sample_methods}")

    remaining = len(skills) - len(skills_for_prompt)
    if remaining > 0:
        descriptions.append(
            "- ... and "
            f"{remaining} more skills. "
            "Use search_skills(query) to find the exact one."
        )

    descriptions.append("")  # trailing newline before next section
    return "\n".join(descriptions)


def _placeholder_for_type(type_hint: str) -> str:
    """Return a sensible placeholder value for a type hint.

    Args:
        type_hint: Lowercase type hint string.

    Returns:
        Placeholder value as a string.
    """
    if not type_hint:
        return "..."
    if "str" in type_hint:
        return "'...'"
    if "int" in type_hint:
        return "0"
    if "float" in type_hint:
        return "0.0"
    if "bool" in type_hint:
        return "True"
    if "list" in type_hint:
        return "[]"
    if "dict" in type_hint:
        return "{}"
    return "..."


# ---------------------------------------------------------------------------
# ToolModeProvider ABC
# ---------------------------------------------------------------------------


class ToolModeProvider(ABC):
    """Base class for tool-mode-specific prompt content.

    Each tool mode (Python exec, TypeScript exec, native tool calling)
    implements this interface to provide the prompt sections that differ
    between modes. The shared composition logic lives in
    :meth:`build_tools_section`.

    To add a new tool mode:
    1. Subclass ``ToolModeProvider``
    2. Implement all abstract methods
    3. Register in :func:`get_tool_mode_provider`
    """

    @abstractmethod
    def tool_header(self) -> str:
        """Return the 'Available Tools' header listing the tools."""

    @abstractmethod
    def discovery_section(self, skill_mode: "SkillMode") -> str:
        """Return instructions for skill discovery (search_skills, etc).

        Args:
            skill_mode: LOCAL or REMOTE.
        """

    @abstractmethod
    def describe_section(self) -> str:
        """Return instructions for describe_function."""

    @abstractmethod
    def execution_section(self, skill_mode: "SkillMode") -> str:
        """Return instructions for skill execution (e.g. python_exec).

        Args:
            skill_mode: LOCAL or REMOTE.
        """

    @abstractmethod
    def examples_section(self, skill_mode: "SkillMode") -> str:
        """Return concrete examples for the LLM.

        Args:
            skill_mode: LOCAL or REMOTE.
        """

    @abstractmethod
    def rules_section(self) -> str:
        """Return execution rules and constraints."""

    @abstractmethod
    def build_example_call(
        self, skill_name: str, method: "SkillMethod",
    ) -> str:
        """Build a ready-to-use example call for describe_function.

        Args:
            skill_name: Name of the skill class.
            method: SkillMethod with structured params.

        Returns:
            Example code string.
        """

    # -- Concrete composition -----------------------------------------------

    def build_tools_section(
        self,
        skill_mode: "SkillMode",
        skills: "List[SkillInfo]",
    ) -> str:
        """Compose all sub-sections into the tools block.

        Subclasses should NOT override this unless they need to
        fundamentally change the section ordering. Override individual
        abstract methods instead.

        Args:
            skill_mode: Current skill mode (LOCAL or REMOTE).
            skills: Loaded skill list (for catalog embedding).

        Returns:
            Complete tools section string.
        """
        parts: list[str] = [
            self.tool_header(),
            self.discovery_section(skill_mode),
            self.describe_section(),
            self.execution_section(skill_mode),
        ]

        # Skill catalog (local only, below threshold)
        if skill_mode == _local_mode() and skills:
            total_fns = _count_total_functions(skills)
            if total_fns <= MAX_FUNCTIONS_FOR_EMBED:
                catalog = _build_local_skill_descriptions(skills)
                if catalog:
                    parts.append(catalog)
            else:
                logger.info(
                    "Total functions (%d) > MAX_FUNCTIONS_FOR_EMBED (%d); "
                    "omitting embedded skill catalog from system prompt.",
                    total_fns,
                    MAX_FUNCTIONS_FOR_EMBED,
                )

        parts.append(self.examples_section(skill_mode))
        parts.append(self.rules_section())
        return "\n\n".join(parts)


def _local_mode() -> "SkillMode":
    """Import and return SkillMode.LOCAL (avoids circular import at class level)."""
    from .sandbox.proxy_gen import SkillMode

    return SkillMode.LOCAL


# ---------------------------------------------------------------------------
# PythonExecToolMode — the current (default) tool mode
# ---------------------------------------------------------------------------


class PythonExecToolMode(ToolModeProvider):
    """Tool mode using ``python_exec`` for skill execution.

    This is the original and default tool mode. The LLM writes Python
    code that calls skills via ``device.<Skill>.<method>(...)`` (local)
    or ``devices.<device>.<Skill>.<method>(...)`` (remote).
    """

    def tool_header(self) -> str:
        """List the 3 available tools."""
        return """\
## Available Tools

You have exactly 3 tools and a set of python skills:
1) search_skills(query) - Find skills by keyword
   (searches method names and descriptions).
2) describe_function(path) - Get the full signature for a skill
   method. Call this if you need more information about a skill
   function, e.g. after an error.
3) python_exec(code) - Execute Python code, including skills."""

    def discovery_section(self, skill_mode: "SkillMode") -> str:
        """Describe search_skills behavior per skill mode."""
        if skill_mode == _local_mode():
            return """\
## search_skills

- search_skills(query) - Find skill functions by keyword.
  Searches method names and descriptions and returns a list of
  skill methods with a short description.
  Example: `search_skills(query="weather")`"""
        return """\
## search_skills

- search_skills(query) - Find skill functions by keyword.
  Returns skill methods, devices they belong to, and a short
  description."""

    def describe_section(self) -> str:
        """Describe describe_function (shared across skill modes)."""
        return """\
## describe_function

- describe_function(path) - Get the full signature and docstring
  for a skill method. Helpful for debugging or when you need more
  information."""

    def execution_section(self, skill_mode: "SkillMode") -> str:
        """Describe python_exec syntax per skill mode."""
        if skill_mode == _local_mode():
            return """\
## python_exec

- Use `python_exec` to execute skills. It takes a string of Python
  code and executes it. The code should call a skill method and
  print the final output. Avoid importing — just use default
  python functions.
- Use the `device` object:
  `device.<SkillClass>.<method>(...)`
- print the final output so the result is surfaced to you.
  Otherwise you won't see a result.
- There is NO object named `default_api`. It does not exist.
  The ONLY way to call skills is: `device.<SkillClass>.<method>(...)`
  inside python_exec.
- Do NOT use `devices.*` or `default_api.*` — they do not exist
  in local mode. Only `device.*` works."""
        return """\
## python_exec

- Use the `devices` object for remote devices:
  `devices.<device>.<SkillClass>.<method>(...)`
- print the final output so the result is surfaced to you.
- Do NOT use `device.*` syntax — it only works in local mode.
  Only `devices.<device>.*` works."""

    def examples_section(self, skill_mode: "SkillMode") -> str:
        """Provide Python-exec examples per skill mode."""
        if skill_mode == _local_mode():
            return """\
## Examples

Weather:
- User: "What's the weather in Seattle?"
  a) search_skills(query="weather")
  b) python_exec(code="print(
     device.WeatherSkill
     .get_current_weather('Seattle'))")

Smart home:
- User: "Set the short lamp to red"
  a) search_skills(query="light")
  b) python_exec(code="print(
     device.HomeAssistantSkill
     .HassLightSet(name='short lamp', color='red'))")

Documentation lookup:
- User: "Look up React docs"
  a) search_skills(query="documentation")
  b) python_exec(code="print(
     device.Context7Skill
     .resolve_library_id(libraryName='react'))")
  c) python_exec(code="print(
     device.Context7Skill
     .query_docs(libraryId='...', query='getting started'))")"""
        # Brief online example so the LLM sees devices.* usage
        return """\
## Example

python_exec(code="print(devices.my_device.WeatherSkill\
.get_current_weather(location='Seattle'))")"""

    def rules_section(self) -> str:
        """Return Python-exec-specific rules."""
        return """\
## Rules

1. Do NOT call skill methods directly as tools — always use
   python_exec. It won't work otherwise.
2. Do NOT output code blocks or ```tool_outputs``` — use python_exec.
3. For smart-home commands (turn on/off, lights, locks, media), look
   for HomeAssistantSkill. Pass the device/entity name as the 'name'
   kwarg.

If there are multiple possible skills, choose the most relevant
and proceed unless you NEED clarification."""

    def build_example_call(
        self, skill_name: str, method: "SkillMethod",
    ) -> str:
        """Build a python_exec example using structured params.

        Uses ``method.params`` (populated at load time from
        ``inspect.signature()``) to produce reliable placeholder args.

        Args:
            skill_name: Name of the skill class.
            method: SkillMethod with structured params.

        Returns:
            Example code string, e.g.
            ``print(device.CalcSkill.add(a=5, b=3))``
        """
        if not method.params:
            return f"print(device.{skill_name}.{method.name}())"

        example_args: list[str] = []
        for p in method.params:
            if p.default is not None:
                # Use actual default, unless it's None — substitute
                # a type-appropriate placeholder more useful to the LLM.
                value = (
                    _placeholder_for_type(p.type_hint.lower())
                    if p.default == "None"
                    else p.default
                )
                example_args.append(f"{p.name}={value}")
            else:
                # Required param — placeholder from type hint
                example_args.append(
                    f"{p.name}={_placeholder_for_type(p.type_hint.lower())}"
                )

        args_str = ", ".join(example_args)
        return f"print(device.{skill_name}.{method.name}({args_str}))"


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

# Singleton instances (stateless, reusable)
_PROVIDERS: dict[str, ToolModeProvider] = {}


def get_tool_mode_provider(name: str = "python_exec") -> ToolModeProvider:
    """Get a tool mode provider by name.

    Providers are cached as singletons since they are stateless.

    Args:
        name: Tool mode name. Currently supported: ``"python_exec"``.

    Returns:
        ToolModeProvider instance.

    Raises:
        ValueError: If the tool mode is unknown.
    """
    if name not in _PROVIDERS:
        if name == "python_exec":
            _PROVIDERS[name] = PythonExecToolMode()
        else:
            raise ValueError(
                f"Unknown tool mode: {name!r}. "
                f"Available: {list(_PROVIDERS.keys()) or ['python_exec']}"
            )
    return _PROVIDERS[name]


# ---------------------------------------------------------------------------
# Public API — backward-compatible composition functions
# ---------------------------------------------------------------------------


def build_tools_section(
    mode: "SkillMode",
    skills: "List[SkillInfo]",
    tool_mode: str = "python_exec",
) -> str:
    """Build the tools/syntax/catalog section for the given mode.

    Delegates to the appropriate :class:`ToolModeProvider`.

    Args:
        mode: Current skill runtime mode (LOCAL or REMOTE).
        skills: Loaded skill list (used for catalog embedding in
            local mode).
        tool_mode: Tool mode name (default ``"python_exec"``).

    Returns:
        Tools section string ready for prompt composition.
    """
    provider = get_tool_mode_provider(tool_mode)
    return provider.build_tools_section(mode, skills)


def build_mode_switch_message(
    to_mode: str,
    skills: List["SkillInfo"] | None = None,
    tool_mode: str = "python_exec",
) -> str:
    """Build a conversation-level message explaining a skill-mode switch.

    Composes a short mode-change notice followed by the full tools
    section so the LLM is re-grounded on available skills and syntax.

    This message is injected into the session as a user-role context
    message so the LLM sees it regardless of which runner (Hub or
    local) processes the next turn.

    Args:
        to_mode: Target mode — ``"online"`` or ``"local"``.
        skills: Loaded skills list. Defaults to ``[]``.
        tool_mode: Tool mode name (default ``"python_exec"``).

    Returns:
        Formatted mode switch notice + tools section string.
    """
    from .sandbox.proxy_gen import SkillMode

    if skills is None:
        skills = []

    if to_mode == "online":
        notice = (
            "[System Notice: Switched to ONLINE mode]\n"
            "Connected to the Hub. Skills from all connected devices "
            "are now available.\n"
            "\n"
            "IMPORTANT: The available skills may differ from before. "
            "Use search_skills to find the correct skill path and "
            "device name before calling anything."
        )
        skill_mode = SkillMode.REMOTE
    else:
        notice = (
            "[System Notice: Switched to LOCAL mode]\n"
            "You are now running locally. All local skills on this device "
            "are fully available and working.\n"
            "\n"
            "IMPORTANT: The available skills may differ from before. "
            "Use search_skills to find the correct skill path before "
            "calling anything."
        )
        skill_mode = SkillMode.LOCAL

    tools = build_tools_section(skill_mode, skills, tool_mode=tool_mode)
    return f"{notice}\n\n{tools}"


def build_tool_mode_switch_message(
    skill_mode: "SkillMode",
    new_tool_mode: str,
    skills: List["SkillInfo"] | None = None,
) -> str:
    """Build a conversation-level message explaining a tool-mode switch.

    Injected when the tool execution mode changes (e.g. Python exec →
    TypeScript exec) without a skill-mode change.

    Args:
        skill_mode: Current skill mode (LOCAL or REMOTE).
        new_tool_mode: New tool mode name.
        skills: Loaded skills list. Defaults to ``[]``.

    Returns:
        Formatted tool mode switch notice + tools section string.
    """
    if skills is None:
        skills = []

    provider = get_tool_mode_provider(new_tool_mode)
    notice = (
        f"[System Notice: Tool mode changed to {new_tool_mode!r}]\n"
        "The way you execute skills has changed. Review the updated "
        "tool instructions below."
    )
    tools = provider.build_tools_section(skill_mode, skills)
    return f"{notice}\n\n{tools}"


def _strip_tool_sections(text: str) -> str:
    """Strip known tool-instruction sections from a custom template.

    Legacy custom templates (saved before the modular refactor) often
    contain the full system prompt including tool sections.  This helper
    removes them so we can cleanly append the dynamically-generated
    tools section without duplication.

    The algorithm walks the text line-by-line.  When it hits a ``##``
    heading that matches a known tool section, it drops all lines until
    the next ``##`` heading or end-of-text.

    Args:
        text: Raw custom template string.

    Returns:
        Template with tool sections removed and trailing whitespace
        cleaned up.
    """
    import re

    # Headers that mark the start of a tool section to strip
    _TOOL_HEADERS = {
        "available tools",
        "search_skills",
        "describe_function",
        "python_exec",
        "ts_exec",
        "examples",
        "example",
        "rules",
        "searching tips",
        "critical notes",
        "available skills",
    }

    lines = text.split("\n")
    result: list[str] = []
    skipping = False

    for line in lines:
        # Check for ## heading
        heading_match = re.match(r"^##\s+(.+)$", line)
        if heading_match:
            heading_text = heading_match.group(1).strip().lower()
            if heading_text in _TOOL_HEADERS:
                skipping = True
                continue
            # A non-tool heading ends any skip block
            skipping = False

        if not skipping:
            result.append(line)

    # Clean up extra blank lines at the end
    cleaned = "\n".join(result).rstrip()
    return cleaned


def build_system_prompt(
    skills: List["SkillInfo"],
    mode: "SkillMode",
    device_name: str,
    custom_template: Optional[str] = None,
    tool_mode: str = "python_exec",
) -> str:
    """Generate the system prompt with skill descriptions.

    Composes ``ROLE_SECTION`` + ``provider.build_tools_section(mode, skills)``
    for the initial system prompt sent to the LLM.

    When *custom_template* is provided it replaces ``ROLE_SECTION`` as
    the personality/behavior section.  Any legacy tool sections embedded
    in the template are stripped automatically (via
    :func:`_strip_tool_sections`) before the canonical tools section is
    appended.

    Args:
        skills: List of loaded SkillInfo objects.
        mode: Current skill runtime mode (LOCAL or REMOTE).
        device_name: Normalized device name (reserved for future use).
        custom_template: Optional custom template.  May contain
            ``{skill_descriptions}`` for catalog injection.  Falls back
            to the composable default.
        tool_mode: Tool mode name (default ``"python_exec"``).

    Returns:
        Complete system prompt string for the LLM.
    """
    from .sandbox.proxy_gen import SkillMode

    tools = build_tools_section(mode, skills, tool_mode=tool_mode)

    # Custom template path — strip legacy tool sections, fill
    # {skill_descriptions}, then append the canonical tools section.
    if custom_template:
        # Strip any baked-in tool sections from legacy templates
        role_only = _strip_tool_sections(custom_template)

        skill_text = ""
        if mode == SkillMode.LOCAL:
            total_fns = _count_total_functions(skills)
            if total_fns <= MAX_FUNCTIONS_FOR_EMBED:
                skill_text = _build_local_skill_descriptions(skills)
            else:
                logger.info(
                    "Total functions (%d) > MAX_FUNCTIONS_FOR_EMBED (%d); "
                    "omitting embedded skill catalog from custom template.",
                    total_fns,
                    MAX_FUNCTIONS_FOR_EMBED,
                )
        try:
            filled = role_only.format(skill_descriptions=skill_text)
        except KeyError:
            logger.warning(
                "Custom system prompt template missing "
                "{skill_descriptions} placeholder; using as-is."
            )
            filled = role_only
        return f"{filled}\n\n{tools}"

    # Default composable path
    return f"{ROLE_SECTION}\n\n{tools}"


# ---------------------------------------------------------------------------
# Backward-compatible convenience (delegates to provider)
# ---------------------------------------------------------------------------


def build_example_call(
    skill_name: str,
    method: "SkillMethod",
    tool_mode: str = "python_exec",
) -> str:
    """Build a ready-to-use example call for a skill method.

    Delegates to the active tool mode provider.

    Args:
        skill_name: Name of the skill class.
        method: SkillMethod with structured params.
        tool_mode: Tool mode name (default ``"python_exec"``).

    Returns:
        Example code string.
    """
    provider = get_tool_mode_provider(tool_mode)
    return provider.build_example_call(skill_name, method)
