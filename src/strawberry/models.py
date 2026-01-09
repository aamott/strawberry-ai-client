"""Shared data models for Strawberry AI Spoke.

This module contains dataclasses that are used across multiple modules
to avoid duplication and ensure consistency.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ChatMessage:
    """A chat message.

    Attributes:
        role: The role of the message sender (user, assistant, system)
        content: The message content
    """

    role: str
    content: str


@dataclass
class ToolCall:
    """A tool call from the LLM.

    Attributes:
        id: Unique identifier for the tool call
        name: Name of the tool/function to call
        arguments: Arguments to pass to the tool
    """

    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatResponse:
    """Unified response from LLM chat endpoints.

    This model supports both Hub and TensorZero responses.
    Hub-only fields default to sensible values.

    Attributes:
        content: The assistant's response text
        model: Model name that generated the response
        finish_reason: Why the response ended (stop, tool_calls, etc.)
        variant: Which variant was used (TensorZero only)
        is_fallback: True if using fallback provider (TensorZero only)
        inference_id: Inference ID for tracking (TensorZero only)
        tool_calls: List of tool calls requested by the model
        raw: Raw response data for debugging
    """

    content: str
    model: str
    finish_reason: str = "stop"
    variant: Optional[str] = None
    is_fallback: bool = False
    inference_id: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)
