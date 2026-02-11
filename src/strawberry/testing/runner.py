"""Custom test runner with clean, minimal output.

Runs tests and shows only what matters:
- Failures + short summary by default (avoids flooding logs / chat context)
- Full pytest output is written to a log file for deeper debugging
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

_HELP_EPILOG = """\
Recommended usage (terminal-friendly):

  # Run tests with minimal console output (full output goes to a log file)
  strawberry-test

  # Verbose output in terminal (full pytest output)
  strawberry-test --show-all

  # Compact output (print only last N lines after the run)
  strawberry-test --tail 120

  # Log reader (no re-run): list failures and show failure N
  strawberry-test --failures
  strawberry-test --show-failure 1

  # Log reader (no re-run): tail the latest log
  strawberry-test --tail-log 200

  # Log reader (no re-run): list log files and search within logs
  strawberry-test --list-logs
  strawberry-test --grep "FAILURES"
  strawberry-test --grep "AssertionError" --after 20
  strawberry-test --grep "test_foo" --from-line 1200 --to-line 1500
"""


def _default_log_file(project_root: Path) -> Path:
    log_dir = project_root / ".test-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "latest.log"


def _project_root() -> Path:
    current = Path(__file__).resolve()
    return current.parent.parent.parent.parent  # src/strawberry/testing -> project root


def _print_header() -> None:
    # Avoid unicode box-drawing chars (Windows cp1252 consoles).
    print("Strawberry AI - Test Runner")
    print("-" * 50)


def _print_help_llm() -> None:
    print("Strawberry AI - Test Runner (LLM Help)")
    print("-")
    print("Run from: ai-pc-spoke/")
    print()
    print("1) Run tests (minimal console output)")
    print("   strawberry-test")
    print()
    print("2) Verbose output (full pytest output in terminal)")
    print("   strawberry-test --show-all")
    print("   strawberry-test -v")
    print("   strawberry-test --tb short")
    print()
    print("3) Compact output (only last N lines after the run)")
    print("   strawberry-test --tail 120")
    print()
    print("4) Log reader (no re-run)")
    print("   strawberry-test --failures")
    print("   strawberry-test --show-failure 1")
    print("   strawberry-test --show-failure 2")
    print("   strawberry-test --tail-log 200")
    print("   strawberry-test --list-logs")
    print('   strawberry-test --grep "FAILURES"')
    print('   strawberry-test --grep "AssertionError" --after 20')
    print('   strawberry-test --grep "test_foo" --from-line 1200 --to-line 1500')
    print()
    print("Log file (default): .test-logs/latest.log")


def _read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _strip_warnings_from_pytest_log(text: str) -> str:
    """Remove pytest warnings sections from a terminal log.

    This is intentionally conservative: it strips the "warnings summary" section
    emitted by pytest (when present) but leaves other content intact.
    """

    lines = text.splitlines(keepends=True)
    out: list[str] = []

    in_warning_section = False
    for line in lines:
        if not in_warning_section and line.strip().lower() == "warnings summary":
            in_warning_section = True
            continue

        # The warnings section ends when pytest prints a new major section title.
        if in_warning_section:
            if _SECTION_TITLE_RE.match(line.rstrip("\n")):
                in_warning_section = False
            else:
                continue

        out.append(line)

    return "".join(out)


def _tail_lines(text: str, line_count: int) -> str:
    if line_count <= 0:
        return ""
    lines = text.splitlines(keepends=True)
    return "".join(lines[-line_count:])


def _list_log_files(log_dir: Path) -> list[Path]:
    if not log_dir.exists():
        return []
    files = [p for p in log_dir.glob("*.log") if p.is_file()]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def _cleanup_log_dir(*, log_dir: Path, keep: Path) -> None:
    """Keep only a single log file in the log directory.

    The repo ignores these logs, so keeping only the newest avoids confusion and
    reduces noise when iterating on one failure at a time.
    """

    if not log_dir.exists():
        return

    keep_resolved = keep.resolve() if keep.exists() else keep
    for p in log_dir.glob("*.log"):
        if not p.is_file():
            continue
        try:
            if p.resolve() == keep_resolved:
                continue
        except FileNotFoundError:
            # Race-y/odd FS edge: if it disappeared, nothing to do.
            continue
        try:
            p.unlink(missing_ok=True)
        except OSError:
            # Best-effort cleanup only.
            pass


def _print_log_files(log_dir: Path) -> int:
    files = _list_log_files(log_dir)
    if not files:
        print(f"No log files found in: {log_dir}")
        return 0

    print(f"Log files in: {log_dir}")
    for p in files:
        print(f"- {p.name}")
    return 0


def _slice_line_range(
    lines: list[str], start_line: int | None, end_line: int | None
) -> list[str]:
    if start_line is None and end_line is None:
        return lines
    start = 1 if start_line is None else max(1, start_line)
    end = len(lines) if end_line is None else min(len(lines), end_line)
    if start > end:
        return []
    return lines[start - 1 : end]


def _search_log(
    *,
    log_file: Path,
    pattern: str,
    fixed_strings: bool,
    ignore_case: bool,
    before: int,
    after: int,
    from_line: int | None,
    to_line: int | None,
) -> int:
    if not log_file.exists():
        print(f"Log file not found: {log_file}")
        return 2

    text = _read_text_file(log_file)
    all_lines = text.splitlines(keepends=False)

    subset = _slice_line_range(all_lines, from_line, to_line)
    offset = 0
    if from_line is not None:
        offset = max(0, from_line - 1)

    flags = re.IGNORECASE if ignore_case else 0
    if fixed_strings:
        regex = re.compile(re.escape(pattern), flags=flags)
    else:
        regex = re.compile(pattern, flags=flags)

    matches: list[int] = []
    for i, line in enumerate(subset, start=1 + offset):
        if regex.search(line):
            matches.append(i)

    if not matches:
        print("No matches found.")
        print(f"Pattern: {pattern}")
        print(f"Log: {log_file}")
        return 1

    printed: set[int] = set()
    for match_line in matches:
        start = max(1, match_line - max(0, before))
        end = min(len(all_lines), match_line + max(0, after))
        for line_no in range(start, end + 1):
            if line_no in printed:
                continue
            printed.add(line_no)
            prefix = ">" if line_no == match_line else " "
            print(f"{prefix}{line_no:6d}: {all_lines[line_no - 1]}")
        print("-")

    print(f"Matches: {len(matches)}")
    print(f"Log: {log_file}")
    return 0


_FAILURE_HEADER_RE = re.compile(r"^_{3,}.*_{3,}\s*$")
_SECTION_TITLE_RE = re.compile(r"^=+\s*([A-Z][A-Z0-9 _-]*)\s*=+\s*$")


def _collect_failure_blocks(section_lines: list[str]) -> list[str]:
    """Split section lines into individual failure blocks."""
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in section_lines:
        if _FAILURE_HEADER_RE.match(line.rstrip("\n")):
            if current:
                blocks.append(current)
            current = [line]
            continue
        if current:
            current.append(line)
    if current:
        blocks.append(current)
    return ["".join(block).rstrip() for block in blocks]


def _extract_failures_from_pytest_log(log_text: str) -> list[str]:
    """Extract individual failure blocks from a pytest log.

    This intentionally uses heuristics based on the default pytest terminal output.
    It's designed to be stable enough for "LLM-readable" terminal workflows.
    """
    lines = log_text.splitlines(keepends=True)
    failures_start: int | None = None
    for i, line in enumerate(lines):
        if line.strip() == "FAILURES":
            failures_start = i
            break

    if failures_start is None:
        return []

    section_lines: list[str] = []
    for line in lines[failures_start + 1 :]:
        match = _SECTION_TITLE_RE.match(line.rstrip("\n"))
        if match is not None:
            title = match.group(1).strip().upper()
            if title != "FAILURES":
                break
        section_lines.append(line)

    return _collect_failure_blocks(section_lines)


def _failure_title(block: str) -> str:
    first_line = block.splitlines()[0] if block else ""
    return first_line.strip("_ ")


def _print_failures_index(log_file: Path) -> int:
    if not log_file.exists():
        print(f"Log file not found: {log_file}")
        return 2

    failures = _extract_failures_from_pytest_log(_read_text_file(log_file))
    if not failures:
        print("No failures found in log.")
        print(f"Log: {log_file}")
        return 0

    print("Failures:")
    for i, block in enumerate(failures, start=1):
        print(f"{i}) {_failure_title(block)}")

    print(f"\nLog: {log_file}")
    return 0


def _print_failure_by_index(log_file: Path, index: int) -> int:
    if not log_file.exists():
        print(f"Log file not found: {log_file}")
        return 2

    failures = _extract_failures_from_pytest_log(_read_text_file(log_file))
    if not failures:
        print("No failures found in log.")
        print(f"Log: {log_file}")
        return 0

    if index < 1 or index > len(failures):
        print(f"Invalid failure index: {index} (valid range: 1..{len(failures)})")
        print(f"Log: {log_file}")
        return 2

    block = failures[index - 1]
    print(f"Failure {index}/{len(failures)}: {_failure_title(block)}")
    print("-" * 50)
    print(block)
    print(f"\nLog: {log_file}")
    return 0


def _build_pytest_command(
    python_exe: str,
    test_dir: Path,
    tb: str,
    verbose: bool,
    passthrough_args: list[str],
) -> list[str]:
    cmd = [python_exe, "-m", "pytest", str(test_dir)]

    # Minimal output by default to keep chat/context clean.
    # -qq removes progress output; failures and a short summary still appear.
    cmd.append("-v" if verbose else "-qq")
    cmd.extend(["--tb", tb])
    cmd.extend(["--color", "no"])
    cmd.extend(["--disable-warnings"])
    cmd.extend(passthrough_args)
    return cmd


def _stream_process_to_log(
    proc: subprocess.Popen,
    log_file: Path,
    show_all: bool,
    tail_lines: int,
) -> int:
    tail: list[str] = []
    tail_cap = max(tail_lines, 0)

    with log_file.open("w", encoding="utf-8", errors="replace", newline="") as f:
        assert proc.stdout is not None
        for line in proc.stdout:
            f.write(line)

            if show_all:
                print(line, end="")
            elif tail_cap > 0:
                tail.append(line)
                if len(tail) > tail_cap:
                    tail.pop(0)

    return_code = proc.wait()

    if not show_all and tail_cap > 0:
        print("\n--- tail of test log ---")
        for line in tail:
            print(line, end="")

    print("\n---")
    print(f"Log: {log_file}")
    return return_code


def _read_log_text(log_file: Path, hide_warnings: bool) -> str:
    """Read a log file and optionally strip warning sections."""
    text = _read_text_file(log_file)
    if hide_warnings:
        text = _strip_warnings_from_pytest_log(text)
    return text


def _cmd_failures(args, log_file: Path) -> int:
    _print_header()
    text = _read_log_text(log_file, args.hide_warnings)
    failures = _extract_failures_from_pytest_log(text)
    if not failures:
        print("No failures found in log.")
        print(f"Log: {log_file}")
        return 0
    print("Failures:")
    for i, block in enumerate(failures, start=1):
        print(f"{i}) {_failure_title(block)}")
    print(f"\nLog: {log_file}")
    return 0


def _cmd_show_failure(args, log_file: Path) -> int:
    _print_header()
    if not log_file.exists():
        print(f"Log file not found: {log_file}")
        return 2
    text = _read_log_text(log_file, args.hide_warnings)
    failures = _extract_failures_from_pytest_log(text)
    if not failures:
        print("No failures found in log.")
        print(f"Log: {log_file}")
        return 0
    index = int(args.show_failure)
    if index < 1 or index > len(failures):
        print(f"Invalid failure index: {index} (valid range: 1..{len(failures)})")
        print(f"Log: {log_file}")
        return 2
    print(f"Failure {index}/{len(failures)}: {_failure_title(failures[index - 1])}")
    print("-" * 50)
    print(failures[index - 1])
    print(f"\nLog: {log_file}")
    return 0


def _cmd_tail_log(args, log_file: Path) -> int:
    _print_header()
    if not log_file.exists():
        print(f"Log file not found: {log_file}")
        return 2
    text = _read_log_text(log_file, args.hide_warnings)
    print(_tail_lines(text, int(args.tail_log)), end="")
    print(f"\nLog: {log_file}")
    return 0


def _parse_line_range(args) -> tuple[int | None, int | None]:
    """Parse from_line/to_line args into optional ints."""
    from_line = int(args.from_line) if int(args.from_line) > 0 else None
    to_line = int(args.to_line) if int(args.to_line) > 0 else None
    return from_line, to_line


def _inline_search(
    text: str,
    pattern: str,
    flags: int,
    before: int,
    after: int,
    from_line: int | None,
    to_line: int | None,
    log_file: Path,
    label: str = "Pattern",
) -> int:
    """Search through already-loaded text and print matches with context."""
    all_lines = text.splitlines(keepends=False)
    subset = _slice_line_range(all_lines, from_line, to_line)
    offset = max(0, (from_line - 1)) if from_line is not None else 0
    regex = re.compile(pattern, flags=flags)
    matches = [i for i, line in enumerate(subset, start=1 + offset) if regex.search(line)]
    if not matches:
        print("No matches found.")
        print(f"{label}: {pattern}" if label == "Pattern" else f"Test: {pattern}")
        print(f"Log: {log_file}")
        return 1
    printed: set[int] = set()
    for match_line in matches:
        start = max(1, match_line - max(0, before))
        end = min(len(all_lines), match_line + max(0, after))
        for line_no in range(start, end + 1):
            if line_no not in printed:
                printed.add(line_no)
                prefix = ">" if line_no == match_line else " "
                print(f"{prefix}{line_no:6d}: {all_lines[line_no - 1]}")
        print("-")
    print(f"Matches: {len(matches)}")
    print(f"Log: {log_file}")
    return 0


def _cmd_test(args, log_file: Path) -> int:
    _print_header()
    from_line, to_line = _parse_line_range(args)
    before = int(args.before) if int(args.before) > 0 else 2
    after = int(args.after) if int(args.after) > 0 else 30

    if not log_file.exists():
        print(f"Log file not found: {log_file}")
        return 2

    if args.hide_warnings:
        text = _read_log_text(log_file, True)
        return _inline_search(
            text,
            re.escape(str(args.test)),
            re.IGNORECASE,
            before,
            after,
            from_line,
            to_line,
            log_file,
            "Test",
        )

    return _search_log(
        log_file=log_file,
        pattern=str(args.test),
        fixed_strings=True,
        ignore_case=True,
        before=before,
        after=after,
        from_line=from_line,
        to_line=to_line,
    )


def _cmd_grep(args, log_file: Path) -> int:
    _print_header()
    from_line, to_line = _parse_line_range(args)
    try:
        if not log_file.exists():
            print(f"Log file not found: {log_file}")
            return 2

        if not args.hide_warnings:
            return _search_log(
                log_file=log_file,
                pattern=str(args.grep),
                fixed_strings=bool(args.fixed_strings),
                ignore_case=bool(args.ignore_case),
                before=int(args.before),
                after=int(args.after),
                from_line=from_line,
                to_line=to_line,
            )

        text = _read_log_text(log_file, True)
        flags = re.IGNORECASE if bool(args.ignore_case) else 0
        pattern = (
            re.escape(str(args.grep)) if bool(args.fixed_strings) else str(args.grep)
        )
        return _inline_search(
            text,
            pattern,
            flags,
            int(args.before),
            int(args.after),
            from_line,
            to_line,
            log_file,
        )
    except re.error as exc:
        print(f"Invalid regex for --grep: {exc}")
        print(f"Pattern: {args.grep}")
        return 2


def _cmd_run_tests(args, passthrough, project_root: Path, log_file: Path) -> int:
    _print_header()
    test_dir = project_root / "tests"
    print(f"Running tests in: {test_dir}")
    print(f"Writing full output to: {log_file}")
    print()
    cmd = _build_pytest_command(
        python_exe=sys.executable,
        test_dir=test_dir,
        tb=args.tb,
        verbose=args.verbose,
        passthrough_args=passthrough,
    )
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    proc = subprocess.Popen(
        cmd,
        cwd=str(project_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    return _stream_process_to_log(
        proc,
        log_file=log_file,
        show_all=bool(args.show_all),
        tail_lines=int(args.tail),
    )


def main() -> int:
    """Run tests with clean output."""
    parser = argparse.ArgumentParser(
        add_help=True,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_HELP_EPILOG,
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Path to write full test output (default: .test-logs/latest.log)",
    )
    parser.add_argument(
        "--help-llm",
        action="store_true",
        help="Print a compact, LLM-friendly help message and exit",
    )
    parser.add_argument(
        "--failures",
        action="store_true",
        help="Read the log file and list failures as: 1) ..., 2) ... (no test run)",
    )
    parser.add_argument(
        "--show-failure",
        type=int,
        default=0,
        help="Read the log file and print failure N with full details (no test run)",
    )
    parser.add_argument(
        "--tail-log",
        type=int,
        default=0,
        help="Read the log file and print last N lines (no test run)",
    )
    parser.add_argument(
        "--list-logs",
        action="store_true",
        help="List available log files under .test-logs (no test run)",
    )
    parser.add_argument(
        "--grep",
        default="",
        help="Search the log file for a pattern (regex by default) (no test run)",
    )
    parser.add_argument(
        "--test",
        default="",
        help=(
            "Convenience search in the log for a test name/nodeid substring "
            "(equivalent to --grep with fixed strings + default context) (no test run)"
        ),
    )
    parser.add_argument(
        "--fixed-strings",
        action="store_true",
        help="Treat --grep as a literal string instead of a regex",
    )
    parser.add_argument(
        "-i",
        "--ignore-case",
        action="store_true",
        help="Case-insensitive search for --grep",
    )
    parser.add_argument(
        "--before",
        type=int,
        default=0,
        help="Print N matching-context lines before each grep match (default: 0)",
    )
    parser.add_argument(
        "--after",
        type=int,
        default=0,
        help="Print N matching-context lines after each grep match (default: 0)",
    )
    parser.add_argument(
        "--from-line",
        type=int,
        default=0,
        help="Only search/print from this 1-based line number (no test run)",
    )
    parser.add_argument(
        "--to-line",
        type=int,
        default=0,
        help="Only search/print up to this 1-based line number (no test run)",
    )
    parser.add_argument(
        "--hide-warnings",
        action="store_true",
        help="Hide pytest warnings sections when reading/searching logs (no test run)",
    )
    parser.add_argument(
        "--show-all",
        action="store_true",
        help="Print full pytest output to console (may be verbose)",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=0,
        help="Print last N lines of the test log after run (default: 0)",
    )
    parser.add_argument(
        "--tb",
        choices=["line", "short", "long", "no"],
        default="line",
        help="Pytest traceback style (default: line)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="More console output (passes -v to pytest)",
    )
    parser.add_argument(
        "--keep-other-logs",
        action="store_true",
        help="Do not delete other .test-logs/*.log files (default keeps only latest)",
    )

    args, passthrough = parser.parse_known_args()

    if args.help_llm:
        _print_help_llm()
        return 0

    project_root = _project_root()
    log_dir = project_root / ".test-logs"
    log_file = Path(args.log_file) if args.log_file else _default_log_file(project_root)
    if not log_file.is_absolute():
        log_file = project_root / log_file
    log_file.parent.mkdir(parents=True, exist_ok=True)

    if log_file.parent == log_dir and not args.keep_other_logs:
        _cleanup_log_dir(log_dir=log_dir, keep=log_file)

    # Dispatch to subcommand handlers
    if args.failures:
        return _cmd_failures(args, log_file)
    if int(args.show_failure) > 0:
        return _cmd_show_failure(args, log_file)
    if int(args.tail_log) > 0:
        return _cmd_tail_log(args, log_file)
    if args.list_logs:
        _print_header()
        return _print_log_files(log_dir)
    if args.test and args.grep:
        _print_header()
        print("Choose either --test or --grep (not both).")
        return 2
    if args.test:
        return _cmd_test(args, log_file)
    if args.grep:
        return _cmd_grep(args, log_file)

    return _cmd_run_tests(args, passthrough, project_root, log_file)


if __name__ == "__main__":
    sys.exit(main())
