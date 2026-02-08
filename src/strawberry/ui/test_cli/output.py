"""Output formatters for test CLI."""

import json
from dataclasses import asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runner import TestResult


class PlainFormatter:
    """Plain text output formatter with full tool visibility."""

    def format_tool_call(self, name: str, arguments: dict) -> str:
        """Format a tool call start.

        Args:
            name: Tool name.
            arguments: Tool arguments dict.

        Returns:
            Formatted string.
        """
        args_str = json.dumps(arguments, indent=2)
        return f"[tool] {name}\n  args: {args_str}"

    def format_tool_result(
        self, name: str, success: bool, result: str | None, error: str | None
    ) -> str:
        """Format a tool call result.

        Args:
            name: Tool name.
            success: Whether call succeeded.
            result: Result text if success.
            error: Error text if failed.

        Returns:
            Formatted string.
        """
        output = result if success else error
        status = "OK" if success else "ERROR"
        # Show full output, no truncation
        return f"  -> [{status}] {output}"

    def format_assistant(self, content: str) -> str:
        """Format assistant response.

        Args:
            content: Assistant message content.

        Returns:
            Formatted string.
        """
        return f"\n[assistant]\n{content}"

    def format_error(self, error: str) -> str:
        """Format an error message.

        Args:
            error: Error text.

        Returns:
            Formatted string.
        """
        return f"[error] {error}"

    def format_system(self, message: str) -> str:
        """Format a system message.

        Args:
            message: System message text.

        Returns:
            Formatted string.
        """
        return f"[system] {message}"

    def format_result(self, result: "TestResult") -> str:
        """Format a complete test result.

        Args:
            result: TestResult object.

        Returns:
            Formatted string.
        """
        lines = []

        # Tool calls
        for tc in result.tool_calls:
            lines.append(self.format_tool_call(tc.name, tc.arguments))
            lines.append(
                self.format_tool_result(tc.name, tc.success, tc.result, tc.error)
            )

        # Assistant response
        if result.response:
            lines.append(self.format_assistant(result.response))

        # Error if any
        if result.error:
            lines.append(self.format_error(result.error))

        # Footer with metadata
        status = "success" if result.success else "failed"
        lines.append(f"\n[{status}] mode={result.mode} duration={result.duration_ms}ms")

        return "\n".join(lines)


class CompactFormatter:
    """Compact output formatter with truncated tool output.

    Reduces verbosity by truncating tool arguments and results to
    a configurable maximum length.
    """

    def __init__(self, max_arg_len: int = 80, max_result_len: int = 120):
        """Initialize compact formatter.

        Args:
            max_arg_len: Maximum length for tool argument display.
            max_result_len: Maximum length for tool result display.
        """
        self.max_arg_len = max_arg_len
        self.max_result_len = max_result_len

    def _truncate(self, text: str, max_len: int) -> str:
        """Truncate text with ellipsis if too long."""
        if len(text) <= max_len:
            return text
        return text[:max_len - 3] + "..."

    def format_tool_call(self, name: str, arguments: dict) -> str:
        """Format a tool call start with truncated arguments."""
        # Compact single-line format
        args_str = ", ".join(f"{k}={repr(v)}" for k, v in arguments.items())
        args_str = self._truncate(args_str, self.max_arg_len)
        return f"[tool] {name}({args_str})"

    def format_tool_result(
        self, name: str, success: bool, result: str | None, error: str | None
    ) -> str:
        """Format a tool call result with truncation."""
        output = result if success else error
        status = "OK" if success else "ERR"
        if output:
            # Remove newlines and truncate
            output = output.replace("\n", " ").strip()
            output = self._truncate(output, self.max_result_len)
        return f"  -> [{status}] {output}"

    def format_assistant(self, content: str) -> str:
        """Format assistant response."""
        return f"\n[assistant] {content}"

    def format_error(self, error: str) -> str:
        """Format an error message."""
        return f"[error] {error}"

    def format_system(self, message: str) -> str:
        """Format a system message."""
        return f"[system] {message}"

    def format_result(self, result: "TestResult") -> str:
        """Format a complete test result with compact output."""
        lines = []

        # Tool calls (compact)
        for tc in result.tool_calls:
            lines.append(self.format_tool_call(tc.name, tc.arguments))
            lines.append(
                self.format_tool_result(tc.name, tc.success, tc.result, tc.error)
            )

        # Assistant response
        if result.response:
            lines.append(self.format_assistant(result.response))

        # Footer with metadata
        status = "OK" if result.success else "FAIL"
        lines.append(f"[{status}] {result.mode} {result.duration_ms}ms")

        return "\n".join(lines)


class JSONFormatter:
    """JSON output formatter for parsing in tests."""

    def format_result(self, result: "TestResult") -> str:
        """Format a complete test result as JSON.

        Args:
            result: TestResult object.

        Returns:
            JSON string.
        """
        data = {
            "success": result.success,
            "response": result.response,
            "error": result.error,
            "tool_calls": [asdict(tc) for tc in result.tool_calls],
            "duration_ms": result.duration_ms,
            "mode": result.mode,
        }
        return json.dumps(data, indent=2)
