"""Input area component for message composition."""

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QTextEdit,
    QToolButton,
    QWidget,
)

from ..utils.icons import Icons


class AutoResizingTextEdit(QTextEdit):
    """Text edit that auto-resizes based on content.

    Expands vertically as the user types, up to a maximum height.
    """

    # Signals
    submit_requested = Signal()  # Emitted when Enter (without Shift) is pressed

    MIN_HEIGHT = 44
    MAX_HEIGHT = 200

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._setup_ui()
        self.textChanged.connect(self._adjust_height)

    def _setup_ui(self) -> None:
        """Initialize the UI."""
        self.setPlaceholderText("Type a message...")
        self.setAcceptRichText(False)
        self.setMinimumHeight(self.MIN_HEIGHT)
        self.setMaximumHeight(self.MIN_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        # Remove frame
        self.setFrameShape(QFrame.Shape.NoFrame)

    def _adjust_height(self) -> None:
        """Adjust height based on content."""
        doc = self.document()
        doc_height = int(doc.size().height())

        # Clamp to min/max
        new_height = max(self.MIN_HEIGHT, min(doc_height + 16, self.MAX_HEIGHT))

        if self.maximumHeight() != new_height:
            self.setMinimumHeight(new_height)
            self.setMaximumHeight(new_height)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle key press events.

        Enter submits, Shift+Enter inserts a newline to support multiline input.
        """
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            modifiers = event.modifiers()
            # Shift+Enter keeps the native newline behavior for multiline messages.
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return

            # Default Enter submits the message.
            self.submit_requested.emit()
            return

        super().keyPressEvent(event)


class InputArea(QFrame):
    """Message input area with voice and send controls.

    Provides a text input field with:
    - Auto-resizing based on content
    - Voice button for speech-to-text (push-to-talk)
    - Attachment button (future)
    - Send button

    Signals:
        submit: Emitted when message is submitted (str: content)
        voice_clicked: Emitted when voice button is clicked
        voice_pressed: Emitted when voice button is pressed (PTT start)
        voice_released: Emitted when voice button is released (PTT stop)
        voice_mode_toggled: Emitted when voice mode is toggled (bool: enabled)
        attach_clicked: Emitted when attach button is clicked
    """

    submit = Signal(str)
    voice_clicked = Signal()
    voice_pressed = Signal()
    voice_released = Signal()
    voice_mode_toggled = Signal(bool)
    attach_clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._voice_mode = False
        self._enabled = True
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Initialize the UI layout."""
        self.setObjectName("InputArea")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # Text input container (for rounded border styling)
        input_container = QFrame()
        input_container.setObjectName("InputContainer")
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(12, 4, 8, 4)
        input_layout.setSpacing(8)

        # Text input
        self._text_input = AutoResizingTextEdit()
        self._text_input.submit_requested.connect(self._on_submit)
        input_layout.addWidget(self._text_input, 1)

        # Voice button (push-to-talk)
        self._voice_btn = QToolButton()
        self._voice_btn.setObjectName("VoiceButton")
        self._voice_btn.setText(Icons.MICROPHONE)
        self._voice_btn.setToolTip("Voice input (hold to speak)")
        self._voice_btn.setCheckable(True)
        self._voice_btn.clicked.connect(self._on_voice_clicked)
        self._voice_btn.pressed.connect(self.voice_pressed.emit)
        self._voice_btn.released.connect(self.voice_released.emit)
        input_layout.addWidget(self._voice_btn)

        # Attach button
        self._attach_btn = QToolButton()
        self._attach_btn.setObjectName("AttachButton")
        self._attach_btn.setText(Icons.ATTACH)
        self._attach_btn.setToolTip("Attach file")
        self._attach_btn.clicked.connect(self.attach_clicked.emit)
        input_layout.addWidget(self._attach_btn)

        # Send button
        self._send_btn = QToolButton()
        self._send_btn.setObjectName("SendButton")
        self._send_btn.setText(Icons.SEND)
        self._send_btn.setToolTip("Send message (Enter)")
        self._send_btn.clicked.connect(self._on_submit)
        input_layout.addWidget(self._send_btn)

        layout.addWidget(input_container, 1)

    def _on_submit(self) -> None:
        """Handle message submission."""
        text = self._text_input.toPlainText().strip()
        if text and self._enabled:
            self.submit.emit(text)
            self.clear()

    def _on_voice_clicked(self) -> None:
        """Handle voice button click."""
        self._voice_mode = self._voice_btn.isChecked()
        self.voice_clicked.emit()
        self.voice_mode_toggled.emit(self._voice_mode)

    def clear(self) -> None:
        """Clear the input text."""
        self._text_input.clear()

    def focus(self) -> None:
        """Focus the input field."""
        self._text_input.setFocus()

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the input area.

        Args:
            enabled: Whether input should be enabled
        """
        self._enabled = enabled
        self._text_input.setEnabled(enabled)
        self._send_btn.setEnabled(enabled)
        self._voice_btn.setEnabled(enabled)
        self._attach_btn.setEnabled(enabled)

    def set_text(self, text: str) -> None:
        """Set the input text.

        Args:
            text: Text to set
        """
        self._text_input.setPlainText(text)

    def get_text(self) -> str:
        """Get the current input text."""
        return self._text_input.toPlainText()

    def set_voice_state(self, listening: bool) -> None:
        """Update the voice button state.

        Args:
            listening: Whether currently listening for voice input
        """
        self._voice_btn.setChecked(listening)
        if listening:
            self._voice_btn.setText(Icons.STOP)
            self._voice_btn.setToolTip("Stop listening")
        else:
            self._voice_btn.setText(Icons.MICROPHONE)
            self._voice_btn.setToolTip("Voice input (hold to speak)")

    def set_placeholder(self, text: str) -> None:
        """Set the placeholder text.

        Args:
            text: Placeholder text to display
        """
        self._text_input.setPlaceholderText(text)

    @property
    def is_voice_mode(self) -> bool:
        """Check if voice mode is active."""
        return self._voice_mode

    @property
    def is_enabled(self) -> bool:
        """Check if input is enabled."""
        return self._enabled
