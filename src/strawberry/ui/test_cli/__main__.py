"""Test CLI entry point.

Usage:
    python -m strawberry.ui.test_cli "What time is it?"
    python -m strawberry.ui.test_cli "message" --json --offline
    python -m strawberry.ui.test_cli --interactive
"""

import argparse
import asyncio
import atexit
import logging
import os
import sys
from pathlib import Path

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


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="test_cli",
        description="Simplified CLI for automated testing of Strawberry Spoke.",
    )

    parser.add_argument(
        "messages",
        nargs="*",
        help="Messages to send (one-shot mode). If empty, runs interactive mode.",
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

    return parser.parse_args()


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
    offline: bool,
    timeout: int,
    config_dir: Path | None,
) -> int:
    """Run one-shot mode with provided messages.

    Args:
        messages: List of messages to send.
        json_output: If True, output JSON.
        quiet: If True, only print final response.
        offline: If True, skip hub connection.
        timeout: Timeout in seconds.
        config_dir: Config directory path.

    Returns:
        Exit code.
    """
    from .output import JSONFormatter, PlainFormatter
    from .runner import TestRunner

    plain_formatter = PlainFormatter()
    json_formatter = JSONFormatter()

    # Create streaming handler (only for non-JSON mode)
    stream_handler = None if json_output else create_stream_handler(plain_formatter, quiet)

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

    Args:
        offline: If True, skip hub connection.
        timeout: Timeout in seconds.
        config_dir: Config directory path.

    Returns:
        Exit code.
    """
    from .output import PlainFormatter
    from .runner import TestRunner

    formatter = PlainFormatter()

    # Create streaming handler for interactive mode
    stream_handler = create_stream_handler(formatter, quiet=False)

    runner = TestRunner(
        config_dir=config_dir,
        offline=offline,
        filter_logs=True,
        on_event=stream_handler,
    )

    try:
        await runner.start()

        mode = "local" if offline else ("online" if runner._core.is_online() else "local")
        print(f"[system] Test CLI ready (mode={mode})")
        print("[system] Type /quit to exit\n")

        while True:
            try:
                # Use aioconsole if available for non-blocking input
                try:
                    from aioconsole import ainput

                    user_input = await ainput("test> ")
                except ImportError:
                    user_input = await asyncio.to_thread(
                        input, "test> "
                    )

                user_input = user_input.strip()
                if not user_input:
                    continue

                if user_input.lower() in ("/quit", "/q", "/exit"):
                    print("[system] Goodbye!")
                    break

                result = await runner.send(user_input, timeout=float(timeout))

                # Just print summary (streaming already handled tool calls)
                status = "success" if result.success else "failed"
                print(
                    f"\n[{status}] mode={result.mode} duration={result.duration_ms}ms\n",
                    flush=True,
                )

            except EOFError:
                break
            except KeyboardInterrupt:
                print("\n[system] Interrupted")
                break

        return EXIT_SUCCESS

    except Exception as e:
        print(f"[error] {e}", file=sys.stderr)
        return EXIT_ERROR

    finally:
        await runner.stop()


def main() -> None:
    """Main entry point."""
    args = parse_args()

    # Determine log file location
    log_dir = Path(__file__).parent.parent.parent.parent.parent / ".test-cli-logs"
    log_file = log_dir / "test_cli.log" if not args.show_logs else None

    configure_logging(show_logs=args.show_logs, log_file=log_file)

    # Determine mode
    if args.interactive or not args.messages:
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
                offline=args.offline,
                timeout=args.timeout,
                config_dir=args.config,
            )
        )

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
