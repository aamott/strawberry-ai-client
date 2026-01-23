"""Chat session state."""

import uuid
from dataclasses import dataclass, field
from typing import List

from ..models import ChatMessage


@dataclass
class ChatSession:
    """Holds state for a single chat session."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    messages: List[ChatMessage] = field(default_factory=list)
    busy: bool = False

    def add_message(self, role: str, content: str) -> ChatMessage:
        """Add a message to the session."""
        msg = ChatMessage(role=role, content=content)
        self.messages.append(msg)
        return msg

    def clear(self) -> None:
        """Clear all messages."""
        self.messages.clear()
