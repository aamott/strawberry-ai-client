"""System prompt generation for the skill service.

Contains the default prompt template and helpers for building
skill descriptions and example calls.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from .loader import SkillInfo, SkillMethod
    from .sandbox.proxy_gen import SkillMode

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Composable system prompt parts
# ---------------------------------------------------------------------------

# Part 1: Core identity + tool list (shared by all modes)
BASE_ROLE_PROMPT = (
    "You are Strawberry, a helpful AI assistant."
)

# The 3 tools are the same in both modes; only the execution target differs.
TOOL_LIST = (
    "## Available Tools\n"
    "\n"
    "You have exactly 3 tools:\n"
    "1. search_skills(query) - Find skills by keyword "
    "(searches method names and descriptions)\n"
    "2. describe_function(path) - Get full signature for a skill method\n"
    "3. python_exec(code) - Execute Python code that calls skills"
)

# Part 2: Mode-specific tool instructions
OFFLINE_TOOL_INSTRUCTIONS = (
    "## How to Call Skills (OFFLINE / LOCAL mode)\n"
    "\n"
    "You only have access to skills on this local device.\n"
    "Execute skills via python_exec with code that calls\n"
    "device.<SkillName>.<method>().\n"
    "\n"
    "- Do NOT use devices.* or device_manager.* (they are unavailable).\n"
    "\n"
    "Examples:\n"
    '- Time: python_exec({{"code": "print(device.TimeSkill.get_current_time())"}})\n'
    '- Weather: python_exec({{"code": "print('
    "  device.WeatherSkill"
    ".get_current_weather('Seattle'))\"}})"
    "\n"
    '- Calculate: python_exec({{"code": "print('
    '  device.CalculatorSkill.add(a=5, b=3))"}})\n'
    '- Smart home: python_exec({{"code": "print(device.HomeAssistantSkill.'
    "HassTurnOn(name='short lamp'))\"}})"
)

# Note: Online tool instructions live in the Hub's skill_service.py
# (DEFAULT_ONLINE_MODE_PROMPT). The Hub owns the online system prompt.

# Part 3: Search tips (shared)
COMMON_SEARCH_TIPS = (
    "## Searching Tips\n"
    "\n"
    "search_skills matches against method names and descriptions.\n"
    "Search by **action** or **verb**, not by specific entity/object names.\n"
    "- To turn on a lamp, search 'turn on' not 'lamp'.\n"
    "- To set brightness, search 'light' or 'brightness'.\n"
    "- To look up docs, search 'documentation' or 'query'.\n"
    "\n"
    "If you already see the right skill in Available"
    " Skills below, skip search_skills\n"
    "and call describe_function or python_exec directly."
)

# Part 4: Rules (shared)
COMMON_RULES = (
    "## Rules\n"
    "\n"
    "1. Use python_exec to call skills - do NOT call"
    " skill methods directly as tools.\n"
    "2. Do NOT output code blocks or ```tool_outputs``` - use actual tool calls.\n"
    "3. Keep responses concise and friendly.\n"
    "4. If you need a skill result, call python_exec"
    " with the appropriate code.\n"
    "5. Do NOT ask the user for permission to use"
    " skills/tools. Use them when needed.\n"
    "6. Do NOT rerun the same tool call to double-check; use the first result.\n"
    "7. After tool calls complete, ALWAYS provide a"
    " final natural-language answer.\n"
    "8. If a tool call fails with 'Unknown tool', immediately switch to python_exec "
    "and proceed.\n"
    "9. For smart-home commands (turn on/off, lights, locks, media), look for "
    "HomeAssistantSkill. Pass the device/entity name as the 'name' kwarg."
)

# ---------------------------------------------------------------------------
# Composed default template (offline mode — used by the Spoke's local runner)
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT_TEMPLATE = (
    f"{BASE_ROLE_PROMPT}\n"
    " You have access to skills on this device.\n"
    "\n"
    f"{TOOL_LIST}\n"
    "\n"
    f"{OFFLINE_TOOL_INSTRUCTIONS}\n"
    "\n"
    f"{COMMON_SEARCH_TIPS}\n"
    "\n"
    "## Available Skills\n"
    "\n"
    "{skill_descriptions}\n"
    "\n"
    f"{COMMON_RULES}"
)


# ---------------------------------------------------------------------------
# Mode switch messages (injected into conversation on mode change)
# ---------------------------------------------------------------------------


def build_mode_switch_message(to_mode: str) -> str:
    """Build a conversation-level message explaining a mode switch.

    This message is injected into the session as a user-role context message
    so the LLM sees it regardless of which runner (Hub or local) processes
    the next turn.

    Args:
        to_mode: Target mode — ``"online"`` or ``"offline"``.

    Returns:
        Formatted mode switch notice string.
    """
    if to_mode == "online":
        return (
            "[System Notice: Switched to ONLINE mode]\n"
            "Connected to the Hub. Skills from all connected devices "
            "are now available.\n"
            "\n"
            "SYNTAX CHANGE — use "
            "`devices.<Device>.<SkillName>.<method>(...)` "
            "(not `device.*`).\n"
            "\n"
            "Your 3 tools still work:\n"
            "- search_skills(query) — find skills across all devices\n"
            "- describe_function(path) — get full signature\n"
            "- python_exec(code) — execute skill calls\n"
            "\n"
            "IMPORTANT: The available skills may differ from before. "
            "Use search_skills to find the correct skill path and "
            "device name before calling anything.\n"
            "\n"
            "Example:\n"
            '  python_exec({"code": "print(devices.my_device.WeatherSkill'
            ".get_current_weather(location='Seattle'))\"})\n"
            "\n"
            "Do NOT use `device.*` syntax (local-only). "
            "Do NOT call skill methods directly as tool calls — "
            "always use python_exec."
        )
    # offline
    return (
        "[System Notice: Switched to LOCAL mode]\n"
        "You are now running locally. All local skills on this device "
        "are fully available and working.\n"
        "\n"
        "SYNTAX CHANGE — use `device.<SkillName>.<method>(...)` "
        "(not `devices.*`).\n"
        "\n"
        "Your 3 tools still work:\n"
        "- search_skills(query) — find available local skills\n"
        "- describe_function(path) — get full signature\n"
        "- python_exec(code) — execute skill calls\n"
        "\n"
        "IMPORTANT: The available skills may differ from before. "
        "Use search_skills to find the correct skill path before "
        "calling anything.\n"
        "\n"
        "Example:\n"
        '  python_exec({"code": "print(device.WeatherSkill'
        ".get_current_weather(location='Seattle'))\"})\n"
        "\n"
        "Do NOT use `devices.*` syntax (Hub is disconnected). "
        "Do NOT call skill methods directly as tool calls — "
        "always use python_exec."
    )


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------


def build_system_prompt(
    skills: List[SkillInfo],
    mode: SkillMode,
    device_name: str,
    custom_template: Optional[str] = None,
    mode_notice: Optional[str] = None,
) -> str:
    """Generate the system prompt with skill descriptions.

    The prompt is composed from :data:`BASE_ROLE_PROMPT`,
    mode-specific tool instructions, skill descriptions,
    and :data:`COMMON_RULES`.

    Args:
        skills: List of loaded SkillInfo objects.
        mode: Current skill runtime mode (LOCAL or REMOTE).
        device_name: Normalized device name for prefix generation.
        custom_template: Optional custom template (must contain
            ``{skill_descriptions}``). Falls back to
            ``DEFAULT_SYSTEM_PROMPT_TEMPLATE``.
        mode_notice: Optional extra notice prepended to the prompt.
            **Deprecated** — prefer injecting a mode-switch message
            into the conversation via :func:`build_mode_switch_message`.

    Returns:
        Complete system prompt string for the LLM.
    """
    from .proxies import normalize_device_name
    from .sandbox.proxy_gen import SkillMode

    if not skills:
        return BASE_ROLE_PROMPT

    mode_lines: list[str] = []
    if mode_notice:
        mode_lines.append(mode_notice.strip())
        mode_lines.append("")

    if mode == SkillMode.LOCAL:
        mode_lines.extend(
            [
                "Runtime mode: OFFLINE/LOCAL.",
                "- Use only the local device proxy:"
                " device.<SkillName>.<method>(...) ",
                "- Do NOT use devices.* or device_manager.* (they are unavailable).",
            ]
        )
    else:
        mode_lines.extend(
            [
                "Runtime mode: ONLINE (Hub).",
                "- Use the remote devices proxy:"
                " devices.<Device>.<SkillName>"
                ".<method>(...) ",
                "- You may also use device_manager.* as a legacy alias.",
            ]
        )

    mode_preamble = "\n".join(mode_lines).strip()

    # Build skill descriptions
    descriptions = []
    for skill in skills:
        descriptions.append(f"### {skill.name}")
        if skill.class_obj.__doc__:
            descriptions.append(skill.class_obj.__doc__.strip())
        descriptions.append("")

        for method in skill.methods:
            prefix = "device"
            if mode == SkillMode.REMOTE:
                prefix = "devices.{device_name}".format(
                    device_name=normalize_device_name(device_name)
                )
            descriptions.append(f"- `{prefix}.{skill.name}.{method.signature}`")
            if method.docstring:
                # Just first line of docstring
                first_line = method.docstring.split("\n")[0].strip()
                descriptions.append(f"  {first_line}")
        descriptions.append("")

    skill_text = "\n".join(descriptions)

    # Use custom system prompt template if set, otherwise default.
    template = custom_template or DEFAULT_SYSTEM_PROMPT_TEMPLATE
    try:
        prompt = template.format(skill_descriptions=skill_text)
    except KeyError:
        # User template is missing {skill_descriptions} — append skills.
        logger.warning(
            "Custom system prompt missing {skill_descriptions} placeholder; "
            "appending skill list."
        )
        prompt = template + "\n\n## Available Skills\n\n" + skill_text

    if mode_preamble:
        return f"{mode_preamble}\n\n{prompt}"
    return prompt


# ---------------------------------------------------------------------------
# Example call helpers
# ---------------------------------------------------------------------------


def build_example_call(skill_name: str, method: SkillMethod) -> str:
    """Build a ready-to-use python_exec example for a skill method.

    Parses the method signature to generate placeholder arguments so the
    LLM can copy-paste and fill in real values.

    Args:
        skill_name: Name of the skill class.
        method: SkillMethod with signature info.

    Returns:
        Example code string, e.g.
        ``print(device.CalcSkill.add(a=5, b=3))``
    """
    sig = method.signature  # e.g. "add(a: int, b: int) -> int"
    # Extract the params portion between parens
    match = re.search(r"\(([^)]*)\)", sig)
    if not match:
        return f"print(device.{skill_name}.{method.name}())"

    params_str = match.group(1).strip()
    if not params_str:
        return f"print(device.{skill_name}.{method.name}())"

    # Parse individual params
    example_args: list[str] = []
    for param in params_str.split(","):
        param = param.strip()
        if not param:
            continue
        # Skip **kwargs params and the bare '*' keyword-only separator
        if param.startswith("**") or param == "*":
            continue

        # Extract name and optional default
        # Formats: "name: type", "name: type = default", "name=default"
        name = param.split(":")[0].split("=")[0].strip()

        # Check for a default value
        if "=" in param:
            default = param.rsplit("=", 1)[1].strip()
            # None defaults are unhelpful for the LLM — use a type placeholder
            if default == "None":
                type_hint = ""
                if ":" in param:
                    type_hint = param.split(":", 1)[1].split("=")[0].strip().lower()
                default = _placeholder_for_type(type_hint)
            example_args.append(f"{name}={default}")
        else:
            # Generate a placeholder based on type hint
            type_hint = ""
            if ":" in param:
                type_hint = param.split(":", 1)[1].split("=")[0].strip().lower()

            placeholder = _placeholder_for_type(type_hint)
            example_args.append(f"{name}={placeholder}")

    args_str = ", ".join(example_args)
    return f"print(device.{skill_name}.{method.name}({args_str}))"


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
