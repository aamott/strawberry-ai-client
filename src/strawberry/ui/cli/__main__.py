"""Strawberry CLI entry point.

Usage:
    strawberry-cli                              # Interactive mode
    strawberry-cli "What time is it?"            # One-shot message
    strawberry-cli "message" --json --offline    # JSON output, offline
    strawberry-cli --settings                    # Settings menu
    strawberry-cli skill-tester                  # Skill interaction tester
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from strawberry.shared.settings import SettingsManager

# Exit codes
EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_TIMEOUT = 2
EXIT_CONFIG_ERROR = 3


def configure_logging(show_logs: bool, log_file: Path | None = None) -> None:
    """Configure logging based on flags.

    Args:
        show_logs: If False, suppress TensorZero/Rust logs.
        log_file: Optional log file path.
    """
    if not show_logs:
        # Silence TensorZero Rust logs - must be set before gateway init
        os.environ["RUST_LOG"] = "off"

        # Redirect stderr to suppress Rust output
        if log_file:
            log_file.parent.mkdir(exist_ok=True)
            stderr_handle = log_file.open("a", encoding="utf-8")
            os.dup2(stderr_handle.fileno(), sys.stderr.fileno())
            sys.stderr = stderr_handle
            atexit.register(stderr_handle.close)
        else:
            # Redirect to /dev/null
            devnull = open(os.devnull, "w")
            os.dup2(devnull.fileno(), sys.stderr.fileno())
            sys.stderr = devnull

    # Configure Python logging
    level = logging.DEBUG if show_logs else logging.WARNING
    handlers = []

    if log_file and show_logs:
        handlers.append(logging.FileHandler(log_file))
    if show_logs:
        handlers.append(logging.StreamHandler(sys.stderr))

    if handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=handlers,
        )

    # Suppress noisy libraries
    for name in ["httpx", "httpcore", "asyncio", "urllib3"]:
        logging.getLogger(name).setLevel(logging.WARNING)


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="strawberry-cli",
        description="Strawberry AI Spoke CLI — chat, settings, and developer tools.",
    )

    parser.add_argument(
        "messages",
        nargs="*",
        help="Messages to send (one-shot mode). Use --interactive for the REPL.",
    )

    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Run interactive REPL instead of one-shot mode.",
    )

    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Output results as JSON.",
    )

    parser.add_argument(
        "--show-logs",
        action="store_true",
        help="Show TensorZero/Rust logs (default: filtered).",
    )

    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip hub connection, force local mode.",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Timeout in seconds per message (default: 120).",
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Config directory path (default: config/).",
    )

    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Only print final assistant response (no tool calls).",
    )

    parser.add_argument(
        "-c",
        "--compact",
        action="store_true",
        help="Compact output: truncate tool args/results to reduce verbosity.",
    )

    parser.add_argument(
        "--settings",
        nargs="*",
        metavar="CMD",
        help="Settings CLI: list, show, get, set, apply, discard, edit, reset",
    )

    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = _build_parser()
    return parser.parse_args(argv)


def create_stream_handler(formatter, quiet: bool):
    """Create a streaming event handler.

    Args:
        formatter: PlainFormatter for output.
        quiet: If True, suppress tool call output.

    Returns:
        Event handler function.
    """

    def handler(event_type: str, data) -> None:
        if quiet:
            return

        if event_type == "tool_start":
            # Print tool call as it starts
            print(formatter.format_tool_call(data.name, data.arguments), flush=True)
        elif event_type == "tool_result":
            # Print result immediately after
            print(
                formatter.format_tool_result(
                    data.name, data.success, data.result, data.error
                ),
                flush=True,
            )
        elif event_type == "assistant":
            # Print assistant response
            print(formatter.format_assistant(data), flush=True)
        elif event_type == "error":
            print(formatter.format_error(data), flush=True)

    return handler


async def run_one_shot(
    messages: list[str],
    json_output: bool,
    quiet: bool,
    compact: bool,
    offline: bool,
    timeout: int,
    config_dir: Path | None,
) -> int:
    """Run one-shot mode with provided messages.

    Args:
        messages: List of messages to send.
        json_output: If True, output JSON.
        quiet: If True, only print final response.
        compact: If True, use compact formatter with truncation.
        offline: If True, skip hub connection.
        timeout: Timeout in seconds.
        config_dir: Config directory path.

    Returns:
        Exit code.
    """
    from .output import CompactFormatter, JSONFormatter, PlainFormatter
    from .runner import TestRunner

    # Select formatter based on flags
    if compact:
        formatter = CompactFormatter()
    else:
        formatter = PlainFormatter()
    json_formatter = JSONFormatter()

    # Create streaming handler (only for non-JSON mode)
    stream_handler = None if json_output else create_stream_handler(formatter, quiet)

    runner = TestRunner(
        config_dir=config_dir,
        offline=offline,
        filter_logs=True,
        on_event=stream_handler,
    )

    try:
        await runner.start()

        exit_code = EXIT_SUCCESS

        for message in messages:
            if not quiet and not json_output:
                print(f"[user] {message}", flush=True)

            result = await runner.send(message, timeout=float(timeout))

            # For JSON mode, print complete result at end
            if json_output:
                print(json_formatter.format_result(result))
            elif quiet:
                # Quiet mode: only final response (not streamed above)
                if result.response:
                    print(result.response)
                elif result.error:
                    print(f"[error] {result.error}", file=sys.stderr)
            else:
                # Streaming mode: just print summary footer
                status = "success" if result.success else "failed"
                print(
                    f"\n[{status}] mode={result.mode} duration={result.duration_ms}ms",
                    flush=True,
                )

            if not result.success:
                if "Timeout" in (result.error or ""):
                    exit_code = EXIT_TIMEOUT
                else:
                    exit_code = EXIT_ERROR

        return exit_code

    except Exception as e:
        print(f"[error] {e}", file=sys.stderr)
        return EXIT_ERROR

    finally:
        await runner.stop()


async def run_interactive(
    offline: bool,
    timeout: int,
    config_dir: Path | None,
) -> int:
    """Run interactive REPL mode.

    Delegates to InteractiveCLI for a full-featured REPL with
    slash commands, voice support, and event notifications.

    Args:
        offline: If True, skip hub connection.
        timeout: Timeout in seconds.
        config_dir: Config directory path.

    Returns:
        Exit code.
    """
    from .interactive import InteractiveCLI

    cli = InteractiveCLI(
        offline=offline,
        timeout=timeout,
        config_dir=config_dir,
    )
    return await cli.run()


def _register_all_schemas(settings: "SettingsManager") -> None:
    """Register SpokeCore and skill settings schemas.

    This is a lightweight alternative to booting full SpokeCore — it
    registers the core schema and discovers skill SETTINGS_SCHEMA from
    the skills directory so ``--settings list`` shows everything.

    Args:
        settings: The SettingsManager to register into.
    """
    # 1. Register SpokeCore schema (with migrations)
    from strawberry.spoke_core.settings_schema import register_spoke_core_schema

    register_spoke_core_schema(settings)

    # 2. Register TensorZero provider settings
    from strawberry.llm.tensorzero_settings import register_tensorzero_schema

    register_tensorzero_schema(settings)

    # 3. Register skills config on Skills tab
    from strawberry.spoke_core.settings_schema import register_skills_config_schema

    register_skills_config_schema(settings)

    # 4. Register GUI appearance settings (themes, font size, etc.)
    from strawberry.ui.gui_v2.settings_schema import register_gui_schema

    register_gui_schema(settings)

    # 5. Discover and register skill settings
    skills_path_str = settings.get("skills_config", "path", "skills")
    skills_path = Path(skills_path_str)
    if not skills_path.is_absolute():
        # Resolve relative to project root
        project_root = Path(__file__).parent.parent.parent.parent.parent
        skills_path = project_root / skills_path

    if skills_path.is_dir():
        from strawberry.skills.loader import SkillLoader

        loader = SkillLoader(skills_path, settings_manager=settings)
        loader.load_all()
        registered = loader.register_skill_settings()
        if registered:
            print(
                f"[info] Discovered settings for {registered} skill(s)",
            )


def run_settings_mode(args: argparse.Namespace) -> int:
    """Run settings CLI mode.

    Args:
        args: Parsed command line arguments.

    Returns:
        Exit code.
    """
    from pathlib import Path

    from strawberry.shared.settings import SettingsManager

    from .settings_cli import run_settings_command

    # Determine config directory
    if args.config:
        config_dir = args.config
    else:
        # Default to config/ relative to project root
        config_dir = Path(__file__).parent.parent.parent.parent.parent / "config"

    if not config_dir.exists():
        print(f"Error: Config directory not found: {config_dir}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    # Initialize settings manager
    settings = SettingsManager(config_dir, auto_save=False)

    # Register core + skill schemas so they appear in listings
    _register_all_schemas(settings)

    # Parse command and args
    settings_args = args.settings or []
    if not settings_args:
        # No subcommand → launch the full interactive menu
        from .settings_menu import run_interactive_menu

        return run_interactive_menu(settings)

    command = settings_args[0]
    cmd_args = settings_args[1:]

    # Route "interactive" to the rich menu
    if command == "interactive":
        from .settings_menu import run_interactive_menu

        return run_interactive_menu(settings)

    return run_settings_command(settings, command, cmd_args)


def _run_skill_tester() -> None:
    """Delegate to the skill interaction tester, forwarding remaining args."""
    from strawberry.testing.skill_tester import main as tester_main

    # Remove 'skill-tester' from argv so the tester's own argparse works
    sys.argv = [sys.argv[0]] + sys.argv[2:]
    tester_main()


def main() -> None:
    """Main entry point."""
    # Intercept 'skill-tester' subcommand before argparse
    if len(sys.argv) > 1 and sys.argv[1] == "skill-tester":
        _run_skill_tester()
        return

    # No arguments → show help instead of launching interactive mode
    if len(sys.argv) == 1:
        _build_parser().print_help()
        sys.exit(EXIT_SUCCESS)

    args = parse_args()

    # Handle settings mode first (doesn't need full SpokeCore)
    if args.settings is not None:
        exit_code = run_settings_mode(args)
        sys.exit(exit_code)

    # Determine log file location
    log_dir = Path(__file__).parent.parent.parent.parent.parent / ".cli-logs"
    log_file = log_dir / "cli.log" if not args.show_logs else None

    configure_logging(show_logs=args.show_logs, log_file=log_file)

    # Determine mode
    if args.interactive:
        exit_code = asyncio.run(
            run_interactive(
                offline=args.offline,
                timeout=args.timeout,
                config_dir=args.config,
            )
        )
    else:
        exit_code = asyncio.run(
            run_one_shot(
                messages=args.messages,
                json_output=args.json,
                quiet=args.quiet,
                compact=args.compact,
                offline=args.offline,
                timeout=args.timeout,
                config_dir=args.config,
            )
        )

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
