"""Shared data models for Strawberry AI Spoke.

This module contains dataclasses that are used across multiple modules
to avoid duplication and ensure consistency.
"""

from dataclasses import dataclass


@dataclass
class ChatMessage:
    """A chat message.

    Attributes:
        role: The role of the message sender (user, assistant, system)
        content: The message content
    """

    role: str
    content: str
