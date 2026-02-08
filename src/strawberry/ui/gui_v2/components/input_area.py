"""Input area component for message composition."""

import time
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
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


# Threshold (ms) to distinguish a tap from a hold on the record button
_HOLD_THRESHOLD_MS = 300


# Loading animation frames for buttons
_RECORD_LOADING_FRAMES = [Icons.MICROPHONE, Icons.LOADING, Icons.MICROPHONE, Icons.LOADING]
_VOICE_MODE_LOADING_FRAMES = [Icons.VOICE_MODE, Icons.LOADING, Icons.VOICE_MODE, Icons.LOADING]


class InputArea(QFrame):
    """Message input area with voice and send controls.

    Provides a text input field with:
    - Auto-resizing based on content
    - Record button: tap to trigger immediate recording (trigger_wakeword),
      hold to push-to-talk (records until released)
    - Voice Mode button: toggles the full voice pipeline (wakeword listening)
    - Attachment button (future)
    - Send button

    Signals:
        submit: Emitted when message is submitted (str: content)
        record_tapped: Emitted on a short tap of the record button (trigger_wakeword)
        record_hold_start: Emitted when record button is held down (PTT start)
        record_hold_stop: Emitted when record button is released after a hold (PTT stop)
        voice_mode_toggled: Emitted when voice mode is toggled (bool: enabled)
        attach_clicked: Emitted when attach button is clicked
    """

    submit = Signal(str)
    record_tapped = Signal()
    record_hold_start = Signal()
    record_hold_stop = Signal()
    voice_mode_toggled = Signal(bool)
    attach_clicked = Signal()

    # Keep legacy signals for backward compat (ChatView forwards these)
    voice_clicked = Signal()
    voice_pressed = Signal()
    voice_released = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._voice_mode = False
        self._enabled = True
        self._recording = False
        self._press_time: Optional[float] = None  # Track press start for hold detection
        # Loading state trackers
        self._record_loading = False
        self._voice_mode_loading = False
        self._record_loading_timer: Optional[QTimer] = None
        self._voice_mode_loading_timer: Optional[QTimer] = None
        self._record_loading_frame = 0
        self._voice_mode_loading_frame = 0
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

        # Record button (tap = trigger_wakeword, hold = push-to-talk)
        self._record_btn = QToolButton()
        self._record_btn.setObjectName("RecordButton")
        self._record_btn.setText(Icons.MICROPHONE)
        self._record_btn.setToolTip("Record (tap to record, hold to push-to-talk)")
        self._record_btn.pressed.connect(self._on_record_pressed)
        self._record_btn.released.connect(self._on_record_released)
        input_layout.addWidget(self._record_btn)

        # Voice Mode button (toggles full pipeline with wakeword)
        self._voice_mode_btn = QToolButton()
        self._voice_mode_btn.setObjectName("VoiceModeButton")
        self._voice_mode_btn.setText(Icons.VOICE_MODE)
        self._voice_mode_btn.setToolTip("Voice mode (wakeword listening)")
        self._voice_mode_btn.setCheckable(True)
        self._voice_mode_btn.clicked.connect(self._on_voice_mode_clicked)
        input_layout.addWidget(self._voice_mode_btn)

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

    # -- Record button (tap vs hold) -----------------------------------------

    def _on_record_pressed(self) -> None:
        """Track when the record button is pressed to detect hold vs tap."""
        self._press_time = time.monotonic()
        self._start_hold_timer()

    def _on_record_released(self) -> None:
        """Determine tap vs hold based on elapsed time since press.

        - Tap (< _HOLD_THRESHOLD_MS): emit record_tapped (trigger_wakeword)
        - Hold (>= _HOLD_THRESHOLD_MS): emit record_hold_stop (PTT stop)
        """
        # Stop the hold timer so it doesn't fire after release
        if hasattr(self, '_hold_timer') and self._hold_timer.isActive():
            self._hold_timer.stop()

        if self._press_time is None:
            return

        elapsed_ms = (time.monotonic() - self._press_time) * 1000
        self._press_time = None

        if self._recording:
            # Was in PTT hold mode — release stops recording
            self._recording = False
            self._record_btn.setText(Icons.MICROPHONE)
            self._record_btn.setToolTip("Record (tap to record, hold to push-to-talk)")
            self.record_hold_stop.emit()
            self.voice_released.emit()  # legacy compat
        elif elapsed_ms < _HOLD_THRESHOLD_MS:
            # Quick tap — trigger immediate recording (VAD decides when to stop)
            self.record_tapped.emit()
            self.voice_clicked.emit()  # legacy compat
        else:
            # Slow-enough press that crossed the hold threshold while we
            # waited — treat it as a hold that just finished (edge case).
            # The hold_start was already emitted via the timer below.
            self._recording = False
            self._record_btn.setText(Icons.MICROPHONE)
            self._record_btn.setToolTip("Record (tap to record, hold to push-to-talk)")
            self.record_hold_stop.emit()
            self.voice_released.emit()  # legacy compat

    def _start_hold_timer(self) -> None:
        """Start a timer to detect hold gesture on the record button."""
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.setInterval(_HOLD_THRESHOLD_MS)
        self._hold_timer.timeout.connect(self._on_hold_threshold)
        self._hold_timer.start()

    def _on_hold_threshold(self) -> None:
        """Called when the hold threshold is reached while still pressed."""
        if self._press_time is not None:
            # Still pressed — enter PTT mode
            self._recording = True
            self._record_btn.setText(Icons.VOICE_LISTENING)
            self._record_btn.setToolTip("Release to stop recording")
            self.record_hold_start.emit()
            self.voice_pressed.emit()  # legacy compat

    # -- Voice Mode button ----------------------------------------------------

    def _on_voice_mode_clicked(self) -> None:
        """Handle voice mode toggle."""
        self._voice_mode = self._voice_mode_btn.isChecked()
        self._update_voice_mode_btn()
        self.voice_mode_toggled.emit(self._voice_mode)

    def _update_voice_mode_btn(self) -> None:
        """Update voice mode button appearance based on state."""
        if self._voice_mode:
            self._voice_mode_btn.setText(Icons.VOICE_MODE_ACTIVE)
            self._voice_mode_btn.setToolTip("Voice mode active (click to stop)")
        else:
            self._voice_mode_btn.setText(Icons.VOICE_MODE)
            self._voice_mode_btn.setToolTip("Voice mode (wakeword listening)")

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
        self._record_btn.setEnabled(enabled)
        self._voice_mode_btn.setEnabled(enabled)
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

    def set_voice_available(self, available: bool) -> None:
        """Enable or disable voice buttons based on VoiceCore availability.

        Args:
            available: Whether VoiceCore is initialized and usable
        """
        self._record_btn.setEnabled(available)
        self._voice_mode_btn.setEnabled(available)
        if not available:
            self._record_btn.setToolTip("Voice engine not available")
            self._voice_mode_btn.setToolTip("Voice engine not available")
        else:
            self._record_btn.setToolTip(
                "Record (tap to record, hold to push-to-talk)"
            )
            self._voice_mode_btn.setToolTip("Voice mode (wakeword listening)")

    def set_recording_state(self, recording: bool) -> None:
        """Update the record button visual state.

        Args:
            recording: Whether currently recording speech
        """
        self._recording = recording
        if recording:
            self._record_btn.setText(Icons.VOICE_LISTENING)
            self._record_btn.setToolTip("Recording...")
        else:
            self._record_btn.setText(Icons.MICROPHONE)
            self._record_btn.setToolTip("Record (tap to record, hold to push-to-talk)")

    def set_voice_mode(self, active: bool) -> None:
        """Update the voice mode button state programmatically.

        Args:
            active: Whether voice mode is active
        """
        self._voice_mode = active
        self._voice_mode_btn.setChecked(active)
        self._update_voice_mode_btn()

    def set_voice_state(self, listening: bool) -> None:
        """Update the voice button state (legacy compat).

        Args:
            listening: Whether currently listening for voice input
        """
        self.set_recording_state(listening)

    def set_placeholder(self, text: str) -> None:
        """Set the placeholder text.

        Args:
            text: Placeholder text to display
        """
        self._text_input.setPlaceholderText(text)

    # -- Loading state for Record button ----------------------------------------

    def set_record_loading(self, loading: bool) -> None:
        """Set the record button to a loading/idle visual state.

        Args:
            loading: True to show a pulsing animation, False to reset.
        """
        self._record_loading = loading
        self._record_btn.setProperty("loading", "true" if loading else "false")
        self._record_btn.style().unpolish(self._record_btn)
        self._record_btn.style().polish(self._record_btn)

        if loading:
            self._record_btn.setEnabled(False)
            self._record_loading_frame = 0
            self._record_loading_timer = QTimer(self)
            self._record_loading_timer.setInterval(400)
            self._record_loading_timer.timeout.connect(self._animate_record_loading)
            self._record_loading_timer.start()
            self._record_btn.setToolTip("Starting voice engine...")
        else:
            if self._record_loading_timer:
                self._record_loading_timer.stop()
                self._record_loading_timer = None
            self._record_btn.setEnabled(True)
            self._record_btn.setText(Icons.MICROPHONE)
            self._record_btn.setToolTip("Record (tap to record, hold to push-to-talk)")

    def _animate_record_loading(self) -> None:
        """Cycle through record button loading animation frames."""
        self._record_btn.setText(
            _RECORD_LOADING_FRAMES[self._record_loading_frame]
        )
        self._record_loading_frame = (
            (self._record_loading_frame + 1) % len(_RECORD_LOADING_FRAMES)
        )

    # -- Loading state for Voice Mode button -----------------------------------

    def set_voice_mode_loading(self, loading: bool) -> None:
        """Set the voice mode button to a loading/idle visual state.

        Args:
            loading: True to show a pulsing animation, False to reset.
        """
        self._voice_mode_loading = loading
        self._voice_mode_btn.setProperty("loading", "true" if loading else "false")
        self._voice_mode_btn.style().unpolish(self._voice_mode_btn)
        self._voice_mode_btn.style().polish(self._voice_mode_btn)

        if loading:
            self._voice_mode_btn.setEnabled(False)
            self._voice_mode_loading_frame = 0
            self._voice_mode_loading_timer = QTimer(self)
            self._voice_mode_loading_timer.setInterval(400)
            self._voice_mode_loading_timer.timeout.connect(
                self._animate_voice_mode_loading
            )
            self._voice_mode_loading_timer.start()
            self._voice_mode_btn.setToolTip("Starting voice engine...")
        else:
            if self._voice_mode_loading_timer:
                self._voice_mode_loading_timer.stop()
                self._voice_mode_loading_timer = None
            self._voice_mode_btn.setEnabled(True)
            self._update_voice_mode_btn()

    def _animate_voice_mode_loading(self) -> None:
        """Cycle through voice mode button loading animation frames."""
        self._voice_mode_btn.setText(
            _VOICE_MODE_LOADING_FRAMES[self._voice_mode_loading_frame]
        )
        self._voice_mode_loading_frame = (
            (self._voice_mode_loading_frame + 1) % len(_VOICE_MODE_LOADING_FRAMES)
        )

    @property
    def is_voice_mode(self) -> bool:
        """Check if voice mode is active."""
        return self._voice_mode

    @property
    def is_recording(self) -> bool:
        """Check if currently recording (PTT hold active)."""
        return self._recording

    @property
    def is_enabled(self) -> bool:
        """Check if input is enabled."""
        return self._enabled
