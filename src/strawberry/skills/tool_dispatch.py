"""Tool dispatch helpers for the skill service.

Contains error enrichment, search result formatting, and the
module-level constants that support tool execution.
"""

from __future__ import annotations

from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Error hints
# ---------------------------------------------------------------------------

# Hints appended to common python_exec errors so the LLM can self-correct.
_ERROR_HINTS: Dict[str, str] = {
    "import": (
        "\nHint: Imports are not allowed in python_exec. "
        "All skill methods are available via device.<SkillName>.<method>()."
    ),
    "__import__": (
        "\nHint: Imports are not allowed in python_exec. "
        "All skill methods are available via device.<SkillName>.<method>()."
    ),
    "open": ("\nHint: File I/O is not allowed in python_exec."),
    "not found": (
        "\nHint: Use search_skills to find available skills, "
        "then describe_function to see the full signature."
    ),
    "not allowed": (
        "\nHint: This operation is restricted for security. "
        "Use device.<SkillName>.<method>() to call skills."
    ),
}


def enrich_exec_error(error: str) -> str:
    """Append an actionable hint to a python_exec error message.

    Scans the error text for known patterns and appends a short hint
    so the LLM can self-correct without extra round-trips.

    Args:
        error: Raw error message string.

    Returns:
        Error string, possibly with an appended hint.
    """
    if not error:
        return error
    error_lower = error.lower()
    for pattern, hint in _ERROR_HINTS.items():
        if pattern in error_lower:
            return error + hint
    return error


# ---------------------------------------------------------------------------
# Search result formatting
# ---------------------------------------------------------------------------


def format_search_results(results: List[Dict[str, Any]]) -> str:
    """Format search results as a compact text table for the LLM.

    Produces one line per result instead of verbose JSON, saving tokens
    and making it easier for the LLM to scan for the right skill.

    Args:
        results: List of dicts with path, signature, summary keys.

    Returns:
        Human/LLM-readable text listing.
    """
    if not results:
        return "No results found."

    lines = [f"Found {len(results)} result(s):"]
    for r in results:
        sig = r.get("signature", r.get("path", "?"))
        summary = r.get("summary", "")
        path = r.get("path", "")
        # Include device info if present (online/Hub results)
        devices = r.get("devices", [])
        device_suffix = ""
        if devices:
            device_suffix = f"  [on: {', '.join(devices[:3])}]"
        line = f"  {path} — {sig}"
        if summary:
            line += f" — {summary}"
        line += device_suffix
        lines.append(line)
    return "\n".join(lines)
