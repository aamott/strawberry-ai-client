"""Agent loop helper utilities for MainWindow.

This module provides common utilities for the agent loops,
reducing duplication between Hub and TensorZero paths.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ...models import ChatMessage


@dataclass
class ToolCallInfo:
    """Information about a tool call execution."""

    iteration: int
    name: str = ""
    code: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)
    success: bool = True
    result: Any = None
    error: Optional[str] = None


@dataclass
class AgentLoopContext:
    """Context for an agent loop execution.

    Tracks state across iterations and provides common operations.
    """

    max_iterations: int = 5
    tool_calls: List[ToolCallInfo] = field(default_factory=list)
    current_iteration: int = 0

    def add_tool_call(self, info: ToolCallInfo) -> None:
        """Record a tool call."""
        self.tool_calls.append(info)

    def get_status_suffix(self) -> str:
        """Get status bar suffix showing tool call count."""
        if self.tool_calls:
            return f" ({len(self.tool_calls)} tool calls)"
        return ""


def build_messages_with_history(
    conversation_history: List[ChatMessage],
    current_message: str,
    system_prompt: Optional[str] = None,
    skip_system_in_history: bool = False,
) -> List[ChatMessage]:
    """Build message list for LLM request.

    Args:
        conversation_history: Previous messages
        current_message: Current user message
        system_prompt: Optional system prompt to prepend
        skip_system_in_history: If True, skip system messages in history

    Returns:
        List of ChatMessage ready for LLM
    """
    messages = []

    # Add system prompt first if provided
    if system_prompt:
        messages.append(ChatMessage(role="system", content=system_prompt))

    # Add conversation history
    for msg in conversation_history:
        if skip_system_in_history and msg.role == "system":
            continue
        messages.append(ChatMessage(role=msg.role, content=msg.content))

    # Add current message
    messages.append(ChatMessage(role="user", content=current_message))

    return messages


def format_tool_output_message(outputs: List[str]) -> str:
    """Format tool outputs for the next LLM iteration.

    Args:
        outputs: List of output strings from tool executions

    Returns:
        Formatted message for LLM
    """
    tool_output = "\n".join(outputs) if outputs else "(no output)"
    return (
        f"[Code executed. Output:]\n{tool_output}\n\n"
        "[Now respond naturally to the user based on this result.]"
    )


def append_in_band_tool_feedback(
    messages: List[ChatMessage],
    *,
    assistant_content: str,
    outputs: List[str],
) -> None:
    """Append tool execution feedback as normal chat messages.

    Some local models (e.g. Ollama fallbacks) do not reliably bind structured
    tool_result blocks to prior tool_calls. In those cases, feeding tool output
    back in-band avoids repeated identical tool calls.
    """
    messages.append(ChatMessage(role="assistant", content=assistant_content))
    messages.append(ChatMessage(role="user", content=format_tool_output_message(outputs)))


def get_final_display_content(
    final_response_content: Optional[str],
    tool_calls: List[ToolCallInfo],
) -> str:
    """Determine final content to display.

    If response is empty but we have tool outputs, show the last result.

    Args:
        final_response_content: Content from final LLM response
        tool_calls: List of tool calls made

    Returns:
        Content to display to user
    """
    if final_response_content:
        return final_response_content

    if tool_calls:
        last = tool_calls[-1]
        if last.success and last.result:
            return str(last.result)
        elif not last.success and last.error:
            return f"Error: {last.error}"
        else:
            return "(Tool executed successfully)"

    return "No response from LLM"
