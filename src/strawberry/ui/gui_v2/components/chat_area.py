"""Chat area component - scrollable message list."""

from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..models.message import Message
from .message_card import MessageCard
from .typing_indicator import TypingIndicator


class ChatArea(QScrollArea):
    """Scrollable area containing message cards.

    Manages a list of MessageCard widgets and provides methods
    for adding, updating, and removing messages. Automatically
    scrolls to the bottom when new messages are added.

    Signals:
        message_clicked: Emitted when a message is clicked (str: message_id)
        scroll_to_bottom_requested: Emitted when scroll to bottom is needed
    """

    message_clicked = Signal(str)
    scroll_to_bottom_requested = Signal()
    read_aloud_requested = Signal(str)  # text content to speak

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._message_cards: Dict[str, MessageCard] = {}
        self._message_order: List[str] = []
        self._auto_scroll = True
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Initialize the UI."""
        self.setObjectName("ChatArea")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFrameShape(QFrame.Shape.NoFrame)

        # Container widget for messages
        self._container = QWidget()
        self._container.setObjectName("ChatContainer")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 8, 0, 8)
        self._layout.setSpacing(0)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Add stretch at the bottom to push messages up
        self._layout.addStretch()

        # Typing indicator (always at bottom, before stretch)
        self._typing_indicator = TypingIndicator()

        self.setWidget(self._container)

        # Connect scroll bar to detect user scrolling
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

    def _on_scroll(self, value: int) -> None:
        """Handle scroll bar value changes."""
        # Check if user scrolled away from bottom
        scrollbar = self.verticalScrollBar()
        at_bottom = value >= scrollbar.maximum() - 50
        self._auto_scroll = at_bottom

    def add_message(self, message: Message) -> MessageCard:
        """Add a new message to the chat.

        Args:
            message: Message model to display

        Returns:
            The created MessageCard widget
        """
        if message.id in self._message_cards:
            # Message already exists, update it instead
            return self._message_cards[message.id]

        card = MessageCard(message=message)
        card.content_changed.connect(self._on_content_changed)
        card.read_aloud_requested.connect(self.read_aloud_requested.emit)

        # Insert before the stretch
        insert_index = self._layout.count() - 1  # Before stretch
        self._layout.insertWidget(insert_index, card)

        self._message_cards[message.id] = card
        self._message_order.append(message.id)

        # Scroll to bottom if auto-scroll is enabled
        if self._auto_scroll:
            QTimer.singleShot(10, self.scroll_to_bottom)

        return card

    def get_message_card(self, message_id: str) -> Optional[MessageCard]:
        """Get a message card by ID.

        Args:
            message_id: ID of the message

        Returns:
            The MessageCard widget, or None if not found
        """
        return self._message_cards.get(message_id)

    def update_message(self, message_id: str, content: str) -> bool:
        """Update a message's text content.

        Args:
            message_id: ID of the message to update
            content: New text content

        Returns:
            True if the message was found and updated
        """
        card = self._message_cards.get(message_id)
        if card:
            card.append_text(content)
            return True
        return False

    def remove_message(self, message_id: str) -> bool:
        """Remove a message from the chat.

        Args:
            message_id: ID of the message to remove

        Returns:
            True if the message was found and removed
        """
        card = self._message_cards.get(message_id)
        if card:
            self._layout.removeWidget(card)
            card.deleteLater()
            del self._message_cards[message_id]
            self._message_order.remove(message_id)
            return True
        return False

    def clear_messages(self) -> None:
        """Remove all messages from the chat."""
        for message_id in list(self._message_cards.keys()):
            self.remove_message(message_id)

    def scroll_to_bottom(self) -> None:
        """Scroll to the bottom of the chat."""
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def scroll_to_message(self, message_id: str) -> bool:
        """Scroll to a specific message.

        Args:
            message_id: ID of the message to scroll to

        Returns:
            True if the message was found
        """
        card = self._message_cards.get(message_id)
        if card:
            self.ensureWidgetVisible(card)
            return True
        return False

    def set_typing(self, is_typing: bool) -> None:
        """Show or hide the typing indicator.

        Args:
            is_typing: Whether to show the typing indicator
        """
        if is_typing:
            # Insert typing indicator before stretch if not already there
            if self._typing_indicator.parent() != self._container:
                insert_index = self._layout.count() - 1
                self._layout.insertWidget(insert_index, self._typing_indicator)
            self._typing_indicator.start()
            if self._auto_scroll:
                QTimer.singleShot(10, self.scroll_to_bottom)
        else:
            self._typing_indicator.stop()

    def _on_content_changed(self) -> None:
        """Handle content changes in message cards."""
        if self._auto_scroll:
            QTimer.singleShot(10, self.scroll_to_bottom)

    def set_auto_scroll(self, enabled: bool) -> None:
        """Enable or disable auto-scroll to bottom.

        Args:
            enabled: Whether to auto-scroll on new messages
        """
        self._auto_scroll = enabled

    @property
    def message_count(self) -> int:
        """Get the number of messages in the chat."""
        return len(self._message_cards)

    @property
    def is_typing(self) -> bool:
        """Check if the typing indicator is active."""
        return self._typing_indicator.is_active
