"""Machine-parseable skill tester for AI coding agents.

Provides the exact same interface the LLM sees (system prompt, tool schemas,
tool call/response cycle) over a JSON-line stdin/stdout protocol. Designed
for an AI coding agent to drive programmatically — no ANSI colors, no
interactive prompts, no decoration.

Protocol:
    - One JSON object per line on stdin (command).
    - One JSON object per line on stdout (response).
    - stderr is used for human-readable status messages during startup.

Commands:
    {"command": "get_system_prompt"}
    {"command": "get_tool_schemas"}
    {"command": "get_skills"}
    {"command": "tool_call", "tool": "<name>", "arguments": {...}}
    {"command": "get_history"}
    {"command": "clear_history"}
    {"command": "save_session", "path": "<filepath>"}
    {"command": "load_session", "path": "<filepath>"}
    {"command": "reload"}
    {"command": "shutdown"}

Responses:
    {"status": "ok", "type": "<type>", "data": ...}
    {"status": "error", "message": "..."}

Usage:
    strawberry-cli skill-tester --agent
    strawberry-cli skill-tester --agent --skills-dir /path/to/skills
    strawberry-cli skill-tester --agent --session session.json  # resume

    # Pipe commands:
    echo '{"command": "get_system_prompt"}' | strawberry-cli skill-tester --agent
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
# History entry (serializable)
# ---------------------------------------------------------------------------


class _HistoryEntry:
    """One tool call + result pair, serializable to/from dict."""

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

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict for JSON output."""
        return {
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "result": self.result,
            "elapsed_ms": round(self.elapsed_ms, 2),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> _HistoryEntry:
        """Deserialize from a dict (e.g. loaded from a session file)."""
        return cls(
            tool_name=d["tool_name"],
            arguments=d["arguments"],
            result=d["result"],
            elapsed_ms=d.get("elapsed_ms", 0.0),
        )


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def _ok(response_type: str, data: Any) -> Dict[str, Any]:
    """Build a success response dict."""
    return {"status": "ok", "type": response_type, "data": data}


def _err(message: str) -> Dict[str, Any]:
    """Build an error response dict."""
    return {"status": "error", "message": message}


def _emit(response: Dict[str, Any]) -> None:
    """Write a single JSON-line response to stdout and flush."""
    sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _log(message: str) -> None:
    """Write a human-readable status line to stderr (not part of protocol)."""
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# Tool schema loader (reused from skill_tester.py, stripped of ANSI)
# ---------------------------------------------------------------------------


def _load_tool_schemas(config_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Load tool JSON schemas from config/tools/.

    Args:
        config_dir: Path to the config directory.

    Returns:
        Dict mapping tool name to its JSON schema.
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
            # Strip internal keys
            schemas[tool_name] = {
                k: v for k, v in schema.items() if not k.startswith("$")
            }
        except Exception as e:
            logger.warning("Failed to load tool schema %s: %s", json_file, e)

    return schemas


# ---------------------------------------------------------------------------
# Agent-mode tester
# ---------------------------------------------------------------------------


class SkillTesterAgent:
    """JSON-line skill tester for AI coding agents.

    Loads skills once, then accepts structured commands on stdin and
    writes structured responses to stdout. Maintains a conversation
    history that can be saved/loaded for session continuity.

    Args:
        skills_dir: Path to the skills directory.
        config_dir: Path to the config directory.
        session_path: Optional path to a session file to auto-load on start.
    """

    def __init__(
        self,
        skills_dir: Optional[Path] = None,
        config_dir: Optional[Path] = None,
        session_path: Optional[Path] = None,
    ) -> None:
        self._project_root = get_project_root()
        self._skills_dir = skills_dir or get_skills_dir()
        self._config_dir = config_dir or (self._project_root / "config")
        self._session_path = session_path

        # Lazy-loaded
        self._service: Optional[SkillService] = None
        self._tool_schemas: Dict[str, Dict[str, Any]] = {}
        self._history: List[_HistoryEntry] = []
        self._skills_loaded = False

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """Load skills and tool schemas if not already done."""
        if self._skills_loaded:
            return

        _log(f"Loading skills from {self._skills_dir} ...")

        self._service = SkillService(
            skills_path=self._skills_dir,
            use_sandbox=False,
            allow_unsafe_exec=True,
        )
        skills = self._service.load_skills()
        self._tool_schemas = _load_tool_schemas(self._config_dir)
        self._skills_loaded = True

        _log(
            f"Ready: {len(skills)} skills, "
            f"{len(self._tool_schemas)} tool schemas loaded."
        )

        # Auto-load session if specified
        if self._session_path and self._session_path.exists():
            loaded = self._load_session(self._session_path)
            _log(f"Resumed session: {loaded} history entries from {self._session_path}")

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def _handle_get_system_prompt(self) -> Dict[str, Any]:
        """Return the exact system prompt the LLM receives."""
        if not self._service:
            return _err("Skills not loaded")
        return _ok("system_prompt", self._service.get_system_prompt())

    def _handle_get_tool_schemas(self) -> Dict[str, Any]:
        """Return tool JSON schemas exactly as sent to the LLM."""
        return _ok("tool_schemas", self._tool_schemas)

    def _handle_get_skills(self) -> Dict[str, Any]:
        """Return structured list of loaded skills and methods."""
        if not self._service:
            return _err("Skills not loaded")

        skills = self._service.get_all_skills()
        result = []
        for skill in skills:
            methods = []
            for method in skill.methods:
                methods.append({
                    "name": method.name,
                    "signature": method.signature,
                    "docstring": method.docstring or "",
                })
            result.append({
                "name": skill.name,
                "docstring": (
                    skill.class_obj.__doc__.strip()
                    if skill.class_obj.__doc__
                    else ""
                ),
                "methods": methods,
            })
        return _ok("skills", result)

    def _handle_tool_call(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a tool call and record it in history.

        Returns the result in the same format the LLM would receive it.
        """
        if not self._service:
            return _err("Skills not loaded")

        start = time.perf_counter()
        result = self._service.execute_tool(tool_name, arguments)
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Record in history
        entry = _HistoryEntry(tool_name, arguments, result, elapsed_ms)
        self._history.append(entry)

        return _ok("tool_result", {
            "tool": tool_name,
            "arguments": arguments,
            # The LLM sees either "result" or "error" — pass through as-is
            **result,
            "elapsed_ms": round(elapsed_ms, 2),
        })

    def _handle_get_history(self) -> Dict[str, Any]:
        """Return the full conversation history (tool calls + results)."""
        return _ok("history", [e.to_dict() for e in self._history])

    def _handle_clear_history(self) -> Dict[str, Any]:
        """Clear the conversation history."""
        count = len(self._history)
        self._history.clear()
        return _ok("clear_history", {"cleared": count})

    def _handle_save_session(self, path: str) -> Dict[str, Any]:
        """Save the current session (history) to a JSON file.

        Args:
            path: File path to write the session to.
        """
        try:
            save_path = Path(path)
            session_data = {
                "version": 1,
                "skills_dir": str(self._skills_dir),
                "history": [e.to_dict() for e in self._history],
            }
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(session_data, f, indent=2, ensure_ascii=False)
            return _ok("save_session", {
                "path": str(save_path),
                "entries": len(self._history),
            })
        except Exception as e:
            return _err(f"Failed to save session: {e}")

    def _load_session(self, path: Path) -> int:
        """Load history from a session file. Returns number of entries loaded."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        entries = data.get("history", [])
        self._history = [_HistoryEntry.from_dict(e) for e in entries]
        return len(self._history)

    def _handle_load_session(self, path: str) -> Dict[str, Any]:
        """Load a previous session from a JSON file.

        Args:
            path: File path to read the session from.
        """
        try:
            load_path = Path(path)
            if not load_path.exists():
                return _err(f"Session file not found: {path}")
            loaded = self._load_session(load_path)
            return _ok("load_session", {
                "path": str(load_path),
                "entries": loaded,
            })
        except Exception as e:
            return _err(f"Failed to load session: {e}")

    def _handle_reload(self) -> Dict[str, Any]:
        """Reload skills from disk."""
        if not self._service:
            return _err("Skills not loaded")

        skills = self._service.reload_skills()
        self._tool_schemas = _load_tool_schemas(self._config_dir)
        return _ok("reload", {
            "skills_count": len(skills),
            "tool_schemas_count": len(self._tool_schemas),
        })

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------

    # Commands that require a "path" argument
    _PATH_COMMANDS = frozenset({"save_session", "load_session"})

    # Commands that need no extra arguments
    _SIMPLE_DISPATCH: Dict[str, str] = {
        "get_system_prompt": "_handle_get_system_prompt",
        "get_tool_schemas": "_handle_get_tool_schemas",
        "get_skills": "_handle_get_skills",
        "get_history": "_handle_get_history",
        "clear_history": "_handle_clear_history",
        "reload": "_handle_reload",
    }

    _VALID_COMMANDS = (
        "get_system_prompt, get_tool_schemas, get_skills, tool_call, "
        "get_history, clear_history, save_session, load_session, "
        "reload, shutdown"
    )

    def dispatch(self, command_obj: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch a single command and return the response.

        This is the main entry point — can be called directly for
        programmatic use, or driven by the stdin loop.

        Args:
            command_obj: Parsed JSON command dict.

        Returns:
            Response dict (ready to be JSON-serialized).
        """
        cmd = command_obj.get("command", "")

        # Simple zero-arg commands
        handler_name = self._SIMPLE_DISPATCH.get(cmd)
        if handler_name:
            return getattr(self, handler_name)()

        # Commands with a required "path" arg
        if cmd in self._PATH_COMMANDS:
            path = command_obj.get("path", "")
            if not path:
                return _err(f"Missing 'path' field in {cmd} command")
            handler = getattr(self, f"_handle_{cmd}")
            return handler(path)

        # tool_call needs tool + arguments
        if cmd == "tool_call":
            tool = command_obj.get("tool", "")
            if not tool:
                return _err("Missing 'tool' field in tool_call command")
            return self._handle_tool_call(tool, command_obj.get("arguments", {}))

        if cmd == "shutdown":
            return _ok("shutdown", {"message": "Shutting down"})

        return _err(
            f"Unknown command: {cmd!r}. Valid commands: {self._VALID_COMMANDS}"
        )

    # ------------------------------------------------------------------
    # Stdin/stdout loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Run the JSON-line protocol loop on stdin/stdout.

        Reads one JSON object per line from stdin, dispatches it,
        and writes one JSON response per line to stdout. Exits on
        EOF, "shutdown" command, or KeyboardInterrupt.
        """
        self._ensure_loaded()

        # Signal readiness on stdout (first line of protocol)
        _emit(_ok("ready", {
            "skills_count": len(self._service.get_all_skills()) if self._service else 0,
            "tool_schemas": list(self._tool_schemas.keys()),
            "session_entries": len(self._history),
            "commands": [
                "get_system_prompt",
                "get_tool_schemas",
                "get_skills",
                "tool_call",
                "get_history",
                "clear_history",
                "save_session",
                "load_session",
                "reload",
                "shutdown",
            ],
        }))

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            # Parse the command
            try:
                command_obj = json.loads(line)
            except json.JSONDecodeError as e:
                _emit(_err(f"Invalid JSON: {e}"))
                continue

            if not isinstance(command_obj, dict):
                _emit(_err("Command must be a JSON object"))
                continue

            # Dispatch
            response = self.dispatch(command_obj)
            _emit(response)

            # Exit on shutdown
            if command_obj.get("command") == "shutdown":
                break


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main(
    skills_dir: Optional[Path] = None,
    config_dir: Optional[Path] = None,
    session_path: Optional[Path] = None,
) -> None:
    """CLI entrypoint for the agent-mode skill tester.

    Args:
        skills_dir: Path to skills directory (None = auto-detect).
        config_dir: Path to config directory (None = auto-detect).
        session_path: Optional session file to resume.
    """
    import argparse

    # Configure logging to file only (stdout is protocol, stderr is status)
    log_dir = get_project_root() / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "skill_tester_agent.log", encoding="utf-8")
        ],
        force=True,
    )
    for name in ("httpx", "httpcore", "asyncio", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(
        description=(
            "Machine-parseable skill tester for AI agents. "
            "Reads JSON commands from stdin, writes JSON responses to stdout."
        ),
    )
    parser.add_argument(
        "--skills-dir",
        type=Path,
        default=skills_dir,
        help="Path to skills directory (default: auto-detect)",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=config_dir,
        help="Path to config directory (default: auto-detect)",
    )
    parser.add_argument(
        "--session",
        type=Path,
        default=session_path,
        help="Session file to resume (loads history on start)",
    )
    args = parser.parse_args()

    agent = SkillTesterAgent(
        skills_dir=args.skills_dir,
        config_dir=args.config_dir,
        session_path=args.session,
    )

    try:
        agent.run()
    except KeyboardInterrupt:
        _log("Interrupted.")
    sys.exit(0)


if __name__ == "__main__":
    main()
