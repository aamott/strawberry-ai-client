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

# If total skill *functions* exceed this threshold, the system prompt
# omits the embedded skill catalog and relies entirely on search_skills
# for tool discovery (Claude tool-search style).
MAX_FUNCTIONS_FOR_EMBED = 30

# When we do embed, cap the number of skill *classes* shown.
MAX_SKILLS_IN_PROMPT = 8


# ---------------------------------------------------------------------------
# Offline (LOCAL) system prompt  — modeled after Hub's updated prompt
# ---------------------------------------------------------------------------

# This is the search-only variant (no embedded skill catalog).
# Used when total functions > MAX_FUNCTIONS_FOR_EMBED.
DEFAULT_SYSTEM_PROMPT_TEMPLATE = """\
You are Strawberry, a helpful AI assistant with access to
skills on this local device.

Skills are pythonic classes that contain methods you can run via
the `python_exec` tool.

## Available Tools

You have exactly 3 tools and a set of python skills:
1) search_skills(query) - Find skills by keyword
   (searches method names and descriptions).
2) describe_function(path) - Get the full signature for a skill
   method. Call this if you need more information about a skill
   function, e.g. after an error.
3) python_exec(code) - Execute Python code, including skills.

## Critical Notes

- There is NO object named `default_api`. It does not exist.
  The ONLY way to call skills is: `device.<SkillClass>.<method>(...)`
  inside python_exec.
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
- If a python_exec call fails, fix the code and retry immediately.
  Do NOT give up or ask the user for help after a single error.
- After tool calls complete, ALWAYS provide a final natural-language
  answer. Where useful, include interim responses ("Let me find that
  for you") to keep the user engaged.

## search_skills

- search_skills(query) - Find skill functions by keyword.
  Searches method names and descriptions and returns a list of
  skill methods with a short description.
  Example: `search_skills(query="weather")`

## describe_function

- describe_function(path) - Get the full signature and docstring
  for a skill method. Helpful for debugging or when you need more
  information.

## python_exec

- Use `python_exec` to execute skills. It takes a string of Python
  code and executes it. The code should call a skill method and
  print the final output. Avoid importing — just use default
  python functions.
- Use the `device` object:
  `device.<SkillClass>.<method>(...)`
- print the final output so the result is surfaced to you.
  Otherwise you won't see a result.
- Do NOT use `devices.*` or `default_api.*` — they do not exist
  in offline mode. Only `device.*` works.

## Searching Tips

search_skills matches against method names, skill names, and
descriptions. Search by **action** or **verb**, not by specific
entity/object names.
- To turn on a lamp, search 'turn on' or 'lamp'.
- To set brightness, search 'light' or 'brightness'.
- If a skill doesn't show up on the first try, continue searching
  and experiment with different keywords.

{skill_descriptions}\

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
     .query_docs(libraryId='...', query='getting started'))")

## Rules

1. Use python_exec to call skills — do NOT call skill methods
   directly as tools. It won't work.
2. Do NOT output code blocks or ```tool_outputs``` — use python_exec.
3. For smart-home commands (turn on/off, lights, locks, media), look
   for HomeAssistantSkill. Pass the device/entity name as the 'name'
   kwarg.

If there are multiple possible skills, choose the most relevant
and proceed unless you NEED clarification.
"""

# Remote-mode template intentionally omits loaded skill listings.
# In online mode, the Hub is authoritative for available skills and
# device routing, so the model should discover via search_skills.
ONLINE_SYSTEM_PROMPT_TEMPLATE = """\
You are Strawberry, a helpful AI assistant connected to the Hub.
You can access skills across all connected devices.

Skills are pythonic classes that contain methods you can run via
the `python_exec` tool.

## Available Tools

You have exactly 3 tools and a set of python skills:
1) search_skills(query) - Find skills by keyword
   (searches method names and descriptions).
2) describe_function(path) - Get the full signature for a skill
   method. Call this if you need more information about a skill
   function, e.g. after an error.
3) python_exec(code) - Execute Python code, including skills.

## Critical Notes

- Try to be helpful. If the user requests something that you suspect
  requires a skill, call `search_skills` to find it.
- Do NOT say "I can't" until you have searched for skills and
  confirmed the skill does not exist. It may take multiple searches.
- After you find the right skill, execute it immediately.
- After tool calls complete, ALWAYS provide a final natural-language
  answer.

## search_skills

- search_skills(query) - Find skill functions by keyword.
  Returns skill methods, devices they belong to, and a short
  description.

## describe_function

- describe_function(path) - Get the full signature and docstring.

## python_exec

- Use the `devices` object for remote devices:
  `devices.<device>.<SkillClass>.<method>(...)`
- print the final output so the result is surfaced to you.
- Do NOT use offline-mode syntax like `device.<Skill>.<method>`.

## Searching Tips

search_skills matches against method names, skill names, and
descriptions. Search by **action** or **verb**.
- If a skill doesn't show up on the first try, continue searching
  and experiment with different keywords.

## Rules

1. Use python_exec to call skills — do NOT call skill methods
   directly as tools. It won't work.
2. Do NOT output code blocks or ```tool_outputs``` — use python_exec.
3. For smart-home commands (turn on/off, lights, locks, media), look
   for HomeAssistantSkill. Pass the device/entity name as 'name'.

If there are multiple possible devices or skills, choose the most
relevant and proceed unless you NEED clarification.
"""


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


def _count_total_functions(skills: List[SkillInfo]) -> int:
    """Count total methods across all loaded skills."""
    return sum(len(s.methods) for s in skills)


def _build_local_skill_descriptions(skills: List[SkillInfo]) -> str:
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


def build_system_prompt(
    skills: List[SkillInfo],
    mode: SkillMode,
    device_name: str,
    custom_template: Optional[str] = None,
    mode_notice: Optional[str] = None,
) -> str:
    """Generate the system prompt with skill descriptions.

    In LOCAL mode the prompt uses ``DEFAULT_SYSTEM_PROMPT_TEMPLATE``.
    If the total number of skill functions is ≤ ``MAX_FUNCTIONS_FOR_EMBED``,
    a compact skill catalog is embedded in the prompt so the LLM can
    skip the search step for common requests.  Above that threshold the
    ``{skill_descriptions}`` placeholder is left empty and the LLM must
    use ``search_skills`` for all discovery (Claude tool-search style).

    In REMOTE mode the prompt uses ``ONLINE_SYSTEM_PROMPT_TEMPLATE``
    which never embeds skills — the Hub is authoritative.

    Args:
        skills: List of loaded SkillInfo objects.
        mode: Current skill runtime mode (LOCAL or REMOTE).
        device_name: Normalized device name for prefix generation.
        custom_template: Optional custom template (must contain
            ``{skill_descriptions}``). Falls back to the mode's
            default template.
        mode_notice: Optional extra notice prepended to the prompt.
            **Deprecated** — prefer injecting a mode-switch message
            into the conversation via :func:`build_mode_switch_message`.

    Returns:
        Complete system prompt string for the LLM.
    """
    from .sandbox.proxy_gen import SkillMode

    # Choose template
    if custom_template:
        template = custom_template
    elif mode == SkillMode.LOCAL:
        template = DEFAULT_SYSTEM_PROMPT_TEMPLATE
    else:
        template = ONLINE_SYSTEM_PROMPT_TEMPLATE

    # Build skill catalog (LOCAL only, below threshold)
    skill_text = ""
    if mode == SkillMode.LOCAL:
        total_fns = _count_total_functions(skills)
        if total_fns <= MAX_FUNCTIONS_FOR_EMBED:
            skill_text = _build_local_skill_descriptions(skills)
        else:
            logger.info(
                "Total functions (%d) > MAX_FUNCTIONS_FOR_EMBED (%d); "
                "omitting embedded skill catalog from system prompt.",
                total_fns,
                MAX_FUNCTIONS_FOR_EMBED,
            )

    # Fill template
    try:
        prompt = template.format(skill_descriptions=skill_text)
    except KeyError:
        logger.warning(
            "System prompt template missing {skill_descriptions} "
            "placeholder; continuing without embedded catalog."
        )
        prompt = template

    # Prepend optional mode notice (deprecated but still supported)
    if mode_notice:
        prompt = f"{mode_notice.strip()}\n\n{prompt}"

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
