"""Interactive CLI tool for testing skill interactions from the LLM's perspective.

Lets a human "be" the LLM: see the exact system prompt, tool schemas, and
issue tool calls (search_skills, describe_function, python_exec) against
real loaded skills. Shows raw results exactly as the LLM would receive them.

Usage:
    python -m strawberry.testing.skill_tester
    python -m strawberry.testing.skill_tester --skills-dir /path/to/skills

Commands (inside the REPL):
    /prompt          - Show the full system prompt the LLM sees
    /tools           - Show tool definitions (JSON schemas)
    /skills          - List all loaded skills and methods
    /reload          - Reload skills from disk
    /history         - Show tool call history for this session
    /clear           - Clear tool call history
    /help            - Show this help
    /quit            - Exit

Tool calls:
    search_skills                     - Search with empty query (list all)
    search_skills weather             - Search for "weather"
    describe_function WeatherSkill.get_current_weather
    python_exec print(device.TimeSkill.get_current_time())
    exec                              - Open multi-line code editor

    You can also call a skill directly for comparison:
    /call CalculatorSkill.add a=5 b=3
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..skills.service import SkillService
from ..utils.paths import get_project_root, get_skills_dir

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ANSI helpers (minimal, self-contained)
# ---------------------------------------------------------------------------


class _C:
    """ANSI color codes."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"


def _s(text: str, *styles: str) -> str:
    """Apply ANSI styles to text."""
    if not styles:
        return text
    return "".join(styles) + text + _C.RESET


# ---------------------------------------------------------------------------
# Tool schema loader
# ---------------------------------------------------------------------------


def _load_tool_schemas(config_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Load tool JSON schemas from config/tools/.

    Args:
        config_dir: Path to the config directory.

    Returns:
        Dict mapping tool name to its JSON schema + description.
    """
    tools_dir = config_dir / "tools"
    schemas: Dict[str, Dict[str, Any]] = {}

    if not tools_dir.is_dir():
        return schemas

    for json_file in sorted(tools_dir.glob("*.json")):
        tool_name = json_file.stem
        try:
            with open(json_file, encoding="utf-8") as f:
                schema = json.load(f)
            schemas[tool_name] = schema
        except Exception as e:
            logger.warning("Failed to load tool schema %s: %s", json_file, e)

    # Also try to load descriptions from tensorzero.toml
    toml_path = config_dir / "tensorzero.toml"
    if toml_path.exists():
        try:
            _enrich_schemas_from_toml(toml_path, schemas)
        except Exception as e:
            logger.debug("Could not parse tensorzero.toml for descriptions: %s", e)

    return schemas


def _enrich_schemas_from_toml(
    toml_path: Path, schemas: Dict[str, Dict[str, Any]]
) -> None:
    """Pull tool descriptions from tensorzero.toml into schemas.

    Args:
        toml_path: Path to tensorzero.toml.
        schemas: Mutable dict of tool schemas to enrich.
    """
    # Simple line-based parser — avoids requiring a toml library
    current_tool: Optional[str] = None
    with open(toml_path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            # Match [tools.<name>]
            if stripped.startswith("[tools.") and stripped.endswith("]"):
                current_tool = stripped[7:-1]  # strip "[tools." and "]"
                continue
            if current_tool and stripped.startswith("description"):
                # description = "..."
                eq_pos = stripped.find("=")
                if eq_pos >= 0:
                    desc = stripped[eq_pos + 1 :].strip().strip('"').strip("'")
                    if current_tool in schemas:
                        schemas[current_tool]["_toml_description"] = desc
                current_tool = None


# ---------------------------------------------------------------------------
# History entry
# ---------------------------------------------------------------------------


class _HistoryEntry:
    """One tool call + result in the session history."""

    def __init__(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: Dict[str, Any],
        elapsed_ms: float,
    ) -> None:
        self.tool_name = tool_name
        self.arguments = arguments
        self.result = result
        self.elapsed_ms = elapsed_ms

    def format_short(self, index: int) -> str:
        """One-line summary."""
        success = "result" in self.result
        icon = _s("✓", _C.GREEN) if success else _s("✗", _C.RED)
        args_preview = ", ".join(f"{k}={repr(v)[:30]}" for k, v in self.arguments.items())
        return (
            f"  {_s(str(index), _C.DIM)}. {icon} "
            f"{_s(self.tool_name, _C.CYAN)}({args_preview}) "
            f"{_s(f'[{self.elapsed_ms:.0f}ms]', _C.DIM)}"
        )


# ---------------------------------------------------------------------------
# Main tester class
# ---------------------------------------------------------------------------


class SkillTester:
    """Interactive skill interaction tester.

    Loads skills, exposes the same tools the LLM sees, and lets a human
    issue tool calls interactively.

    Args:
        skills_dir: Path to the skills directory.
        config_dir: Path to the config directory (for tool schemas).
    """

    def __init__(
        self,
        skills_dir: Optional[Path] = None,
        config_dir: Optional[Path] = None,
    ) -> None:
        self._project_root = get_project_root()
        self._skills_dir = skills_dir or get_skills_dir()
        self._config_dir = config_dir or (self._project_root / "config")

        # Core components
        self._service: Optional[SkillService] = None
        self._tool_schemas: Dict[str, Dict[str, Any]] = {}
        self._history: List[_HistoryEntry] = []

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load skills and tool schemas."""
        print(_s("\nLoading skills...", _C.DIM))

        self._service = SkillService(
            skills_path=self._skills_dir,
            use_sandbox=False,  # Direct execution for testing
            allow_unsafe_exec=True,
        )
        skills = self._service.load_skills()

        print(
            _s(f"  Loaded {len(skills)} skills from ", _C.DIM)
            + _s(str(self._skills_dir), _C.YELLOW)
        )
        for skill in skills:
            methods = ", ".join(m.name for m in skill.methods)
            print(f"    {_s(skill.name, _C.CYAN)}: {_s(methods, _C.DIM)}")

        # Load tool schemas
        self._tool_schemas = _load_tool_schemas(self._config_dir)
        print(_s(f"  Loaded {len(self._tool_schemas)} tool schemas", _C.DIM))
        print()

    def _reload(self) -> None:
        """Reload skills from disk."""
        if self._service:
            skills = self._service.reload_skills()
            print(_s(f"Reloaded {len(skills)} skills", _C.GREEN))
            for skill in skills:
                methods = ", ".join(m.name for m in skill.methods)
                print(f"  {_s(skill.name, _C.CYAN)}: {_s(methods, _C.DIM)}")
        else:
            self._load()

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def _show_prompt(self) -> None:
        """Display the full system prompt the LLM receives."""
        if not self._service:
            print(_s("Skills not loaded", _C.RED))
            return

        prompt = self._service.get_system_prompt()
        print(
            _s(
                "\n═══ SYSTEM PROMPT (exactly as the LLM sees it) ═══\n",
                _C.MAGENTA,
                _C.BOLD,
            )
        )
        print(prompt)
        print(_s("\n═══ END SYSTEM PROMPT ═══\n", _C.MAGENTA, _C.BOLD))

    def _show_tools(self) -> None:
        """Display tool definitions (JSON schemas)."""
        if not self._tool_schemas:
            print(_s("No tool schemas loaded", _C.RED))
            return

        print(
            _s(
                "\n═══ TOOL DEFINITIONS (JSON schemas sent to LLM) ═══\n",
                _C.MAGENTA,
                _C.BOLD,
            )
        )
        for name, schema in self._tool_schemas.items():
            toml_desc = schema.pop("_toml_description", None)
            print(_s(f"── {name} ──", _C.CYAN, _C.BOLD))
            if toml_desc:
                print(_s(f"  tensorzero.toml: {toml_desc}", _C.DIM))
                schema["_toml_description"] = toml_desc  # restore
            # Print the schema without the internal key
            display = {k: v for k, v in schema.items() if not k.startswith("_")}
            print(json.dumps(display, indent=2))
            print()
        print(_s("═══ END TOOL DEFINITIONS ═══\n", _C.MAGENTA, _C.BOLD))

    def _show_skills(self) -> None:
        """List all loaded skills and their methods."""
        if not self._service:
            print(_s("Skills not loaded", _C.RED))
            return

        skills = self._service.get_all_skills()
        print(_s(f"\n{len(skills)} skills loaded:\n", _C.BOLD))
        for skill in skills:
            print(f"  {_s(skill.name, _C.CYAN, _C.BOLD)}")
            if skill.class_obj.__doc__:
                print(
                    f"    {_s(skill.class_obj.__doc__.strip().split(chr(10))[0], _C.DIM)}"
                )
            for method in skill.methods:
                print(f"    - {_s(method.signature, _C.GREEN)}")
                if method.docstring:
                    first_line = method.docstring.strip().split("\n")[0]
                    print(f"      {_s(first_line, _C.DIM)}")
        print()

    def _show_history(self) -> None:
        """Show tool call history."""
        if not self._history:
            print(_s("No tool calls yet", _C.DIM))
            return

        print(_s(f"\nTool call history ({len(self._history)} calls):\n", _C.BOLD))
        for i, entry in enumerate(self._history, 1):
            print(entry.format_short(i))
        print()

    def _show_help(self) -> None:
        """Show help text."""
        help_text = """
Commands:
  /prompt          Show the full system prompt the LLM sees
  /tools           Show tool definitions (JSON schemas)
  /skills          List all loaded skills and methods
  /reload          Reload skills from disk
  /history         Show tool call history
  /clear           Clear tool call history
  /help            Show this help
  /quit            Exit

Tool calls (type directly):
  search_skills                          Search all skills (empty query)
  search_skills weather                  Search for "weather"
  describe_function WeatherSkill.get_current_weather
  python_exec print(device.TimeSkill.get_current_time())
  exec                                   Multi-line code editor

Direct skill call (for comparison with python_exec output):
  /call CalculatorSkill.add a=5 b=3
"""
        print(_s(help_text, _C.CYAN))

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    def _execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool call and record it in history.

        Args:
            tool_name: Tool name (search_skills, describe_function, python_exec).
            arguments: Tool arguments dict.

        Returns:
            Result dict with "result" or "error" key.
        """
        if not self._service:
            return {"error": "Skills not loaded"}

        # Show what we're calling
        args_str = json.dumps(arguments, indent=2) if arguments else "{}"
        print(_s("\n▶ Calling tool: ", _C.CYAN) + _s(tool_name, _C.CYAN, _C.BOLD))
        print(_s(f"  Arguments: {args_str}", _C.DIM))

        # Execute with timing
        start = time.perf_counter()
        result = self._service.execute_tool(tool_name, arguments)
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Record history
        entry = _HistoryEntry(tool_name, arguments, result, elapsed_ms)
        self._history.append(entry)

        # Display result
        self._display_tool_result(result, elapsed_ms)
        return result

    def _display_tool_result(self, result: Dict[str, Any], elapsed_ms: float) -> None:
        """Display a tool result exactly as the LLM would see it.

        Args:
            result: Dict with "result" or "error".
            elapsed_ms: Execution time in milliseconds.
        """
        timing = _s(f"[{elapsed_ms:.0f}ms]", _C.DIM)

        if "error" in result:
            print(_s("\n◀ TOOL ERROR ", _C.RED, _C.BOLD) + timing)
            print(_s("─" * 60, _C.RED))
            print(result["error"])
            print(_s("─" * 60, _C.RED))
        else:
            print(_s("\n◀ TOOL RESULT ", _C.GREEN, _C.BOLD) + timing)
            print(_s("─" * 60, _C.GREEN))
            print(result.get("result", "(no output)"))
            print(_s("─" * 60, _C.GREEN))

        # Show the raw type and length for awareness
        raw = result.get("result", result.get("error", ""))
        print(
            _s(f"  Raw type: {type(raw).__name__}, length: {len(str(raw))} chars", _C.DIM)
        )
        print()

    # ------------------------------------------------------------------
    # Direct skill call (for comparison)
    # ------------------------------------------------------------------

    def _direct_call(self, call_str: str) -> None:
        """Call a skill method directly (bypassing python_exec) for comparison.

        Format: SkillName.method_name arg1=val1 arg2=val2

        Args:
            call_str: The call string after "/call ".
        """
        if not self._service:
            print(_s("Skills not loaded", _C.RED))
            return

        parts = call_str.strip().split()
        if not parts:
            print(_s("Usage: /call SkillName.method_name arg1=val1 arg2=val2", _C.YELLOW))
            return

        path = parts[0]
        path_parts = path.split(".")
        if len(path_parts) != 2:
            print(_s("Path must be SkillName.method_name", _C.RED))
            return

        skill_name, method_name = path_parts

        # Parse kwargs
        kwargs: Dict[str, Any] = {}
        for arg in parts[1:]:
            if "=" not in arg:
                print(_s(f"Invalid argument format: {arg} (expected key=value)", _C.RED))
                return
            key, val_str = arg.split("=", 1)
            # Try to parse as Python literal
            try:
                val = json.loads(val_str)
            except (json.JSONDecodeError, ValueError):
                val = val_str
            kwargs[key] = val

        print(
            _s("\n▶ Direct call: ", _C.MAGENTA)
            + _s(f"{skill_name}.{method_name}({kwargs})", _C.MAGENTA, _C.BOLD)
        )

        start = time.perf_counter()
        try:
            result = self._service._loader.call_method(skill_name, method_name, **kwargs)
            elapsed_ms = (time.perf_counter() - start) * 1000

            print(
                _s("\n◀ DIRECT RESULT ", _C.MAGENTA, _C.BOLD)
                + _s(f"[{elapsed_ms:.0f}ms]", _C.DIM)
            )
            print(_s("─" * 60, _C.MAGENTA))
            print(repr(result))
            print(_s("─" * 60, _C.MAGENTA))
            rlen = len(repr(result))
            print(
                _s(
                    f"  Type: {type(result).__name__}, repr length: {rlen} chars",
                    _C.DIM,
                )
            )

            # Now show what python_exec would return for comparison
            kw_str = ", ".join(f"{k}={repr(v)}" for k, v in kwargs.items())
            code = f"print(device.{skill_name}.{method_name}({kw_str}))"
            print(_s("\n  Equivalent python_exec code:", _C.DIM))
            print(_s(f"    {code}", _C.YELLOW))

            exec_result = self._service.execute_tool("python_exec", {"code": code})
            exec_output = exec_result.get("result", exec_result.get("error", ""))
            print(_s("  python_exec would return:", _C.DIM))
            print(f"    {exec_output}")

            # Compare
            direct_str = str(result)
            exec_str = str(exec_output).strip()
            if direct_str == exec_str:
                print(_s("  ✓ Outputs match", _C.GREEN))
            else:
                print(_s("  ⚠ Outputs differ!", _C.YELLOW, _C.BOLD))
                print(_s(f"    Direct: {repr(direct_str)}", _C.DIM))
                print(_s(f"    Exec:   {repr(exec_str)}", _C.DIM))

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            print(_s(f"\n  Error: {e}", _C.RED))
            print(_s(f"  [{elapsed_ms:.0f}ms]", _C.DIM))

        print()

    # ------------------------------------------------------------------
    # Input parsing
    # ------------------------------------------------------------------

    def _read_multiline_code(self) -> str:
        """Read multi-line Python code from stdin.

        The user types code line by line and ends with 'END' on its own line.

        Returns:
            The joined code string.
        """
        print(_s("Enter Python code (type END on its own line to finish):", _C.YELLOW))
        print(_s("  You have access to: device.<SkillName>.<method>(), print()", _C.DIM))
        lines: list[str] = []
        while True:
            try:
                line = input(_s("... ", _C.YELLOW))
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if line.strip().upper() == "END":
                break
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _strip_call_parens(text: str) -> str:
        """Remove surrounding parentheses from a call-style argument."""
        if text.startswith("(") and text.endswith(")"):
            return text[1:-1].strip()
        return text

    @staticmethod
    def _strip_kw_prefix(text: str, prefix: str) -> str:
        """Strip a keyword prefix like 'query=' or 'code=' and surrounding quotes."""
        if text.startswith(prefix):
            return text[len(prefix) :].strip().strip('"').strip("'")
        return text

    def _parse_search_skills(self, rest: str) -> tuple[str, Dict[str, Any]]:
        rest = self._strip_call_parens(rest)
        query = self._strip_kw_prefix(rest, "query=")
        return ("search_skills", {"query": query})

    def _parse_describe_function(self, rest: str) -> Optional[tuple[str, Dict[str, Any]]]:
        rest = self._strip_call_parens(rest)
        rest = self._strip_kw_prefix(rest, "path=")
        if not rest:
            print(_s("Usage: describe_function SkillName.method_name", _C.YELLOW))
            return None
        return ("describe_function", {"path": rest})

    def _parse_python_exec(self, rest: str) -> Optional[tuple[str, Dict[str, Any]]]:
        rest = self._strip_call_parens(rest)
        rest = self._strip_kw_prefix(rest, "code=")
        if rest.startswith("{") and rest.endswith("}"):
            try:
                parsed = json.loads(rest)
                rest = parsed.get("code", rest)
            except json.JSONDecodeError:
                pass
        if not rest:
            rest = self._read_multiline_code()
        return ("python_exec", {"code": rest}) if rest.strip() else None

    def _parse_tool_call(self, user_input: str) -> Optional[tuple[str, Dict[str, Any]]]:
        """Parse user input into a tool call.

        Supported formats:
            search_skills / search_skills weather / search_skills query="weather"
            describe_function WeatherSkill.get_current_weather
            python_exec print(device.TimeSkill.get_current_time())
            exec  (opens multi-line editor)

        Args:
            user_input: Raw user input string.

        Returns:
            Tuple of (tool_name, arguments) or None if not a tool call.
        """
        stripped = user_input.strip()
        if not stripped:
            return None

        if stripped.lower() == "exec":
            code = self._read_multiline_code()
            return ("python_exec", {"code": code}) if code.strip() else None

        # Dispatch by prefix
        lower = stripped.lower()
        tool_parsers: list[tuple[str, Any]] = [
            ("search_skills", self._parse_search_skills),
            ("describe_function", self._parse_describe_function),
            ("python_exec", self._parse_python_exec),
        ]
        for prefix, parser in tool_parsers:
            if lower.startswith(prefix):
                rest = stripped[len(prefix) :].strip()
                return parser(rest)

        return None

    # ------------------------------------------------------------------
    # Main REPL
    # ------------------------------------------------------------------

    def _dispatch_slash_command(self, stripped: str) -> bool:
        """Handle a slash command. Returns True to continue, False to quit."""
        cmd = stripped.lower().split()[0]

        # Dispatch table for simple commands
        simple_cmds: dict[str, Any] = {
            "/prompt": self._show_prompt,
            "/tools": self._show_tools,
            "/skills": self._show_skills,
            "/reload": self._reload,
            "/history": self._show_history,
            "/help": self._show_help,
        }
        if cmd in ("/quit", "/q", "/exit"):
            print(_s("Goodbye!", _C.DIM))
            return False
        if cmd in simple_cmds:
            simple_cmds[cmd]()
        elif cmd == "/clear":
            self._history.clear()
            print(_s("History cleared", _C.DIM))
        elif cmd == "/call":
            self._direct_call(stripped[5:].strip())
        else:
            print(_s(f"Unknown command: {cmd}. Type /help for help.", _C.RED))
        return True

    def _print_tool_help(self) -> None:
        """Print available tool call formats."""
        print(_s("Not recognized as a tool call. Available tools:", _C.YELLOW))
        for line in [
            "  search_skills [query]",
            "  describe_function SkillName.method_name",
            "  python_exec <code>",
            "  exec  (multi-line editor)",
            "  /call SkillName.method arg=val  (direct comparison)",
        ]:
            print(_s(line, _C.CYAN))

    def run(self) -> None:
        """Run the interactive REPL."""
        self._print_banner()
        self._load()
        self._show_help()

        while True:
            try:
                user_input = input(_s("llm> ", _C.BLUE, _C.BOLD))
            except (EOFError, KeyboardInterrupt):
                print(_s("\nGoodbye!", _C.DIM))
                break

            stripped = user_input.strip()
            if not stripped:
                continue

            if stripped.startswith("/"):
                if not self._dispatch_slash_command(stripped):
                    break
                continue

            parsed = self._parse_tool_call(stripped)
            if parsed:
                self._execute_tool(*parsed)
            else:
                self._print_tool_help()

    def _print_banner(self) -> None:
        """Print the welcome banner."""
        print(_s("\n╭──────────────────────────────────────────────╮", _C.CYAN))
        print(
            _s("│", _C.CYAN)
            + _s("  Skill Interaction Tester", _C.CYAN, _C.BOLD)
            + "                     "
            + _s("│", _C.CYAN)
        )
        print(
            _s("│", _C.CYAN)
            + _s("  Be the LLM — test tool calls interactively", _C.DIM)
            + "  "
            + _s("│", _C.CYAN)
        )
        print(_s("╰──────────────────────────────────────────────╯", _C.CYAN))


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entrypoint for the skill tester."""
    import argparse

    # Configure logging to file (not console)
    log_dir = get_project_root() / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(log_dir / "skill_tester.log", encoding="utf-8")],
        force=True,
    )
    # Suppress noisy loggers on console
    for name in ("httpx", "httpcore", "asyncio", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(
        description="Interactive skill interaction tester — be the LLM",
    )
    parser.add_argument(
        "--skills-dir",
        type=Path,
        default=None,
        help="Path to skills directory (default: auto-detect)",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help="Path to config directory (default: auto-detect)",
    )
    args = parser.parse_args()

    tester = SkillTester(
        skills_dir=args.skills_dir,
        config_dir=args.config_dir,
    )

    try:
        tester.run()
    except KeyboardInterrupt:
        print()
    sys.exit(0)


if __name__ == "__main__":
    main()
