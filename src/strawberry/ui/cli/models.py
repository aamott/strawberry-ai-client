"""Models for the CLI UI layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class ToolCallSummary:
    """Summary details for a tool call.

    Args:
        name: Tool name.
        arguments: Tool arguments payload.
        preview: Short preview string for display.
    """

    name: str
    arguments: Dict[str, Any]
    preview: str


@dataclass
class ToolResultPayload:
    """Details for a tool result payload.

    Args:
        tool_name: Tool name.
        content: Full tool output.
        preview: Preview string for collapsed display.
        success: Whether the tool result was successful.
        error: Optional error text.
    """

    tool_name: str
    content: str
    preview: str
    success: bool = True
    error: Optional[str] = None
