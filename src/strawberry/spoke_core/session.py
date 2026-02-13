"""Chat session state."""

import uuid
from dataclasses import dataclass, field
from typing import List, Optional

from ..models import ChatMessage


@dataclass
class ChatSession:
    """Holds state for a single chat session.

    Attributes:
        last_mode: The mode ("online" or "offline") when the last message
            was processed. ``None`` means no message has been sent yet.
            Used to detect mode switches mid-conversation.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    messages: List[ChatMessage] = field(default_factory=list)
    busy: bool = False
    last_mode: Optional[str] = None

    def add_message(self, role: str, content: str) -> ChatMessage:
        """Add a message to the session."""
        msg = ChatMessage(role=role, content=content)
        self.messages.append(msg)
        return msg

    def clear(self) -> None:
        """Clear all messages."""
        self.messages.clear()
