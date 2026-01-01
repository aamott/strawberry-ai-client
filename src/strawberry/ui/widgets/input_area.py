"""Message input area with send button and mic button."""

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QTextEdit, QWidget

from ..theme import Theme


class MicState:
    """Mic button states."""
    IDLE = "idle"           # Not recording, ready to start
    RECORDING = "recording"  # Currently recording
    PROCESSING = "processing"  # Processing recorded audio


class InputTextEdit(QTextEdit):
    """Text edit that emits signal on Ctrl+Enter or Enter (configurable)."""

    submit_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.enter_sends = True  # Enter sends, Shift+Enter for newline

    def keyPressEvent(self, event: QKeyEvent):
        """Handle key press events."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Check modifiers
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                # Shift+Enter: insert newline
                super().keyPressEvent(event)
            elif event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                # Ctrl+Enter: always submit
                self.submit_requested.emit()
            elif self.enter_sends:
                # Plain Enter: submit (if enabled)
                self.submit_requested.emit()
            else:
                # Plain Enter: newline
                super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)


class InputArea(QWidget):
    """Input area with text field, send button, and mic button.
    
    Signals:
        message_submitted(str): Emitted when user submits a message
        mic_clicked: Emitted when mic button is clicked (toggle recording)
    """

    message_submitted = Signal(str)
    mic_clicked = Signal()

    def __init__(
        self,
        theme: Optional[Theme] = None,
        placeholder: str = "Type a message...",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        self._theme = theme
        self._placeholder = placeholder
        self._sending = False
        self._mic_state = MicState.IDLE
        self._mic_visible = True

        self._setup_ui()

    def _setup_ui(self):
        """Set up the input area."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 16)
        layout.setSpacing(12)

        # Mic button (prominent, for push-to-talk)
        self._mic_btn = QPushButton("🎤")
        self._mic_btn.setObjectName("micRecordButton")
        self._mic_btn.setFixedSize(44, 44)
        self._mic_btn.setToolTip("Click to record voice message")
        self._mic_btn.clicked.connect(self._on_mic_clicked)
        self._mic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self._mic_btn)

        # Text input
        self._text_edit = InputTextEdit()
        self._text_edit.setPlaceholderText(self._placeholder)
        self._text_edit.setMinimumHeight(44)
        self._text_edit.setMaximumHeight(150)
        self._text_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Minimum
        )
        self._text_edit.submit_requested.connect(self._on_submit)

        # Make text edit grow with content
        self._text_edit.textChanged.connect(self._adjust_height)

        layout.addWidget(self._text_edit)

        # Send button
        self._send_btn = QPushButton("Send")
        self._send_btn.setMinimumWidth(80)
        self._send_btn.setMinimumHeight(44)
        self._send_btn.clicked.connect(self._on_submit)
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        layout.addWidget(self._send_btn)

        # Apply theme
        if self._theme:
            self._apply_theme()

    def _apply_theme(self):
        """Apply theme styling."""
        if not self._theme:
            return

        self.setStyleSheet(f"""
            InputArea {{
                background-color: {self._theme.bg_secondary};
                border-top: 1px solid {self._theme.border};
            }}
            
            QPushButton#micRecordButton {{
                background-color: {self._theme.bg_tertiary};
                border: 2px solid {self._theme.border};
                border-radius: 22px;
                font-size: 18px;
            }}
            
            QPushButton#micRecordButton:hover {{
                background-color: {self._theme.accent};
                border-color: {self._theme.accent};
            }}
            
            QPushButton#micRecordButton[recording="true"] {{
                background-color: {self._theme.error};
                border-color: {self._theme.error};
                animation: pulse 1s infinite;
            }}
            
            QPushButton#micRecordButton[processing="true"] {{
                background-color: {self._theme.warning};
                border-color: {self._theme.warning};
            }}
        """)

    def _adjust_height(self):
        """Adjust text edit height based on content."""
        doc_height = self._text_edit.document().size().height()
        # Add some padding
        new_height = min(max(44, int(doc_height) + 24), 150)
        self._text_edit.setMinimumHeight(new_height)

    def _on_submit(self):
        """Handle message submission."""
        if self._sending:
            return

        text = self._text_edit.toPlainText().strip()
        if not text:
            return

        # Clear input
        self._text_edit.clear()

        # Emit signal
        self.message_submitted.emit(text)

    def set_sending(self, sending: bool):
        """Set sending state (disables input during send)."""
        self._sending = sending
        self._send_btn.setEnabled(not sending)
        self._text_edit.setEnabled(not sending)

        if sending:
            self._send_btn.setText("...")
        else:
            self._send_btn.setText("Send")

    def set_focus(self):
        """Focus the text input."""
        self._text_edit.setFocus()

    def set_theme(self, theme: Theme):
        """Update theme."""
        self._theme = theme
        self._apply_theme()

    def _on_mic_clicked(self):
        """Handle mic button click."""
        self.mic_clicked.emit()

    def set_mic_state(self, state: str):
        """Set the mic button state.
        
        Args:
            state: One of MicState.IDLE, MicState.RECORDING, MicState.PROCESSING
        """
        self._mic_state = state

        # Update button appearance via properties
        self._mic_btn.setProperty("recording", state == MicState.RECORDING)
        self._mic_btn.setProperty("processing", state == MicState.PROCESSING)

        # Update tooltip
        if state == MicState.RECORDING:
            self._mic_btn.setToolTip("Click to stop recording")
            self._mic_btn.setText("⏹️")
        elif state == MicState.PROCESSING:
            self._mic_btn.setToolTip("Processing...")
            self._mic_btn.setText("⏳")
        else:
            self._mic_btn.setToolTip("Click to record voice message")
            self._mic_btn.setText("🎤")

        # Force style refresh
        self._mic_btn.style().unpolish(self._mic_btn)
        self._mic_btn.style().polish(self._mic_btn)

    def set_mic_visible(self, visible: bool):
        """Show or hide the mic button."""
        self._mic_visible = visible
        self._mic_btn.setVisible(visible)

    def set_mic_enabled(self, enabled: bool):
        """Enable or disable the mic button."""
        self._mic_btn.setEnabled(enabled)

