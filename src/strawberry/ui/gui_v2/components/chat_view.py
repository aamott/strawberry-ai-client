"""Chat view component - main chat container."""

import logging
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..models.message import Message
from .chat_area import ChatArea
from .input_area import InputArea

logger = logging.getLogger(__name__)


class OfflineBanner(QFrame):
    """Banner shown when running in offline mode."""

    dismissed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Initialize the UI."""
        from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton

        from ..utils.icons import Icons

        self.setObjectName("OfflineBanner")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        # Warning icon and message
        self._label = QLabel(
            f"{Icons.WARNING} Running locally. Some features may be limited."
        )
        layout.addWidget(self._label, 1)

        # Dismiss button
        self._dismiss_btn = QToolButton()
        self._dismiss_btn.setText(Icons.CLOSE)
        self._dismiss_btn.setToolTip("Dismiss")
        self._dismiss_btn.clicked.connect(self._on_dismiss)
        layout.addWidget(self._dismiss_btn)

    def _on_dismiss(self) -> None:
        """Handle dismiss button click."""
        self.hide()
        self.dismissed.emit()


class ChatView(QWidget):
    """Main chat view container.

    Contains the chat area (scrollable messages), optional offline banner,
    and input area. Coordinates between these components.

    Signals:
        message_sent: Emitted when user sends a message (str: content)
        record_tapped: Emitted when record button is tapped (trigger_wakeword)
        record_hold_start: Emitted when record button is held (PTT start)
        record_hold_stop: Emitted when record button is released after hold (PTT stop)
        voice_mode_toggled: Emitted when voice mode is toggled (bool: enabled)
        voice_requested: Emitted when voice button is clicked (legacy)
        voice_pressed: Emitted when voice button is pressed (legacy)
        voice_released: Emitted when voice button is released (legacy)
        attachment_requested: Emitted when attach button is clicked
    """

    message_sent = Signal(str)
    record_tapped = Signal()
    record_hold_start = Signal()
    record_hold_stop = Signal()
    voice_mode_toggled = Signal(bool)
    voice_requested = Signal()
    voice_pressed = Signal()
    voice_released = Signal()
    attachment_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._offline_mode = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Initialize the UI layout."""
        self.setObjectName("ChatView")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Offline banner (hidden by default)
        self._offline_banner = OfflineBanner()
        self._offline_banner.hide()
        layout.addWidget(self._offline_banner)

        # Chat area (scrollable messages)
        self._chat_area = ChatArea()
        layout.addWidget(self._chat_area, 1)

        # Input area
        self._input_area = InputArea()
        self._input_area.submit.connect(self._on_message_submit)
        # New voice signals
        self._input_area.record_tapped.connect(self.record_tapped.emit)
        self._input_area.record_hold_start.connect(self.record_hold_start.emit)
        self._input_area.record_hold_stop.connect(self.record_hold_stop.emit)
        self._input_area.voice_mode_toggled.connect(self.voice_mode_toggled.emit)
        # Legacy voice signals
        self._input_area.voice_clicked.connect(self.voice_requested.emit)
        self._input_area.voice_pressed.connect(self.voice_pressed.emit)
        self._input_area.voice_released.connect(self.voice_released.emit)
        self._input_area.attach_clicked.connect(self.attachment_requested.emit)
        layout.addWidget(self._input_area)

    def _on_message_submit(self, content: str) -> None:
        """Handle message submission from input area."""
        self.message_sent.emit(content)

    def add_message(self, message: Message) -> None:
        """Add a message to the chat.

        Args:
            message: Message model to display
        """
        self._chat_area.add_message(message)

    def get_message_card(self, message_id: str):
        """Get a message card by ID.

        Args:
            message_id: ID of the message

        Returns:
            The MessageCard widget, or None if not found
        """
        return self._chat_area.get_message_card(message_id)

    def update_message(self, message_id: str, content: str) -> bool:
        """Update a message's text content.

        Args:
            message_id: ID of the message to update
            content: New text content

        Returns:
            True if the message was found and updated
        """
        return self._chat_area.update_message(message_id, content)

    def clear_messages(self) -> None:
        """Remove all messages from the chat."""
        self._chat_area.clear_messages()

    def scroll_to_bottom(self) -> None:
        """Scroll to the bottom of the chat."""
        self._chat_area.scroll_to_bottom()

    def set_typing(self, is_typing: bool) -> None:
        """Show or hide the typing indicator.

        Args:
            is_typing: Whether to show the typing indicator
        """
        self._chat_area.set_typing(is_typing)

    def set_input_enabled(self, enabled: bool) -> None:
        """Enable or disable the input area.

        Args:
            enabled: Whether input should be enabled
        """
        self._input_area.set_enabled(enabled)

    def set_input_text(self, text: str) -> None:
        """Set the input text.

        Args:
            text: Text to set in the input area
        """
        self._input_area.set_text(text)

    def clear_input(self) -> None:
        """Clear the input text."""
        self._input_area.clear()

    def focus_input(self) -> None:
        """Focus the input field."""
        self._input_area.focus()

    def set_offline_mode(self, offline: bool) -> None:
        """Show or hide the offline mode banner.

        Args:
            offline: Whether running in offline mode
        """
        self._offline_mode = offline
        self._offline_banner.setVisible(offline)

    def set_voice_state(self, listening: bool) -> None:
        """Update the voice button state (legacy compat).

        Args:
            listening: Whether currently listening for voice input
        """
        self._input_area.set_voice_state(listening)

    def set_recording_state(self, recording: bool) -> None:
        """Update the record button visual state.

        Args:
            recording: Whether currently recording speech
        """
        self._input_area.set_recording_state(recording)

    def set_voice_mode(self, active: bool) -> None:
        """Update the voice mode button state programmatically.

        Args:
            active: Whether voice mode is active
        """
        self._input_area.set_voice_mode(active)

    def set_voice_available(self, available: bool) -> None:
        """Enable or disable voice buttons based on VoiceCore availability.

        Args:
            available: Whether VoiceCore is initialized and usable
        """
        self._input_area.set_voice_available(available)

    def set_record_loading(self, loading: bool) -> None:
        """Set the record button to a loading/idle visual state.

        Args:
            loading: True to show a pulsing animation, False to reset.
        """
        self._input_area.set_record_loading(loading)

    def set_voice_mode_loading(self, loading: bool) -> None:
        """Set the voice mode button to a loading/idle visual state.

        Args:
            loading: True to show a pulsing animation, False to reset.
        """
        self._input_area.set_voice_mode_loading(loading)

    @property
    def chat_area(self) -> ChatArea:
        """Get the chat area component."""
        return self._chat_area

    @property
    def input_area(self) -> InputArea:
        """Get the input area component."""
        return self._input_area

    @property
    def is_offline_mode(self) -> bool:
        """Check if offline mode is active."""
        return self._offline_mode

    @property
    def is_typing(self) -> bool:
        """Check if the typing indicator is active."""
        return self._chat_area.is_typing
