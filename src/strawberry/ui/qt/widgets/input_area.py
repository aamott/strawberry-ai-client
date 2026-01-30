"""Message input area with send button, mic button, and voice mode button."""

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QTextEdit, QWidget

from ..theme import Theme


class VoiceButtonState:
    """Voice button states (shared by mic and voice mode buttons)."""

    IDLE = "idle"  # Ready to start
    LOADING = "loading"  # Initializing voice system
    LISTENING = "listening"  # Waiting for wake word / listening for speech
    RECORDING = "recording"  # Recording speech
    PROCESSING = "processing"  # Processing recorded audio
    SPEAKING = "speaking"  # TTS playing


# Backwards compatibility alias
MicState = VoiceButtonState


class MicButton(QPushButton):
    """Animated mic button with loading spinner and recording waveform.

    States:
    - IDLE: Shows mic icon (🎤)
    - LOADING: Grayed out with spinning arc animation
    - RECORDING: Red background with animated waveform bars
    - PROCESSING: Orange with static waveform
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._state = VoiceButtonState.IDLE
        self._theme: Optional[Theme] = None
        self._spin_angle = 0.0
        self._waveform_phase = 0.0
        self._animation_timer_id: Optional[int] = None

        # No text - we draw everything custom
        self.setText("")

    def set_theme(self, theme: Theme):
        """Apply theme styling."""
        self._theme = theme
        self._update_style()

    def _update_style(self):
        """Update stylesheet based on current state."""
        if not self._theme:
            return

        if self._state == VoiceButtonState.LOADING:
            # Grayed out while loading
            self.setStyleSheet(f"""
                MicButton {{
                    background-color: {self._theme.bg_tertiary};
                    border: 2px solid {self._theme.border};
                    border-radius: 20px;
                }}
            """)
        elif self._state == VoiceButtonState.RECORDING:
            # Red while recording
            self.setStyleSheet(f"""
                MicButton {{
                    background-color: #ffebee;
                    border: 2px solid {self._theme.error};
                    border-radius: 20px;
                }}
            """)
        elif self._state == VoiceButtonState.PROCESSING:
            # Orange while processing
            self.setStyleSheet(f"""
                MicButton {{
                    background-color: #fff3e0;
                    border: 2px solid {self._theme.warning};
                    border-radius: 20px;
                }}
            """)
        else:
            # Default idle state - show mic icon via paint
            self.setStyleSheet(f"""
                MicButton {{
                    background-color: {self._theme.bg_tertiary};
                    border: 1px solid {self._theme.border};
                    border-radius: 20px;
                }}
                MicButton:hover {{
                    background-color: {self._theme.accent};
                    border-color: {self._theme.accent};
                }}
            """)

    def set_state(self, state: str):
        """Set the button state."""
        old_state = self._state
        self._state = state

        # Update tooltip
        tooltips = {
            VoiceButtonState.IDLE: "Speech to text",
            VoiceButtonState.LOADING: "Starting voice system...",
            VoiceButtonState.RECORDING: "Recording... click to stop",
            VoiceButtonState.PROCESSING: "Processing speech...",
        }
        self.setToolTip(tooltips.get(state, "Speech to text"))

        self._update_style()

        # Start/stop animation
        needs_animation = state in (
            VoiceButtonState.LOADING,
            VoiceButtonState.RECORDING,
            VoiceButtonState.PROCESSING,
        )
        had_animation = old_state in (
            VoiceButtonState.LOADING,
            VoiceButtonState.RECORDING,
            VoiceButtonState.PROCESSING,
        )

        if needs_animation and not had_animation:
            self._start_animation()
        elif not needs_animation and had_animation:
            self._stop_animation()

        self.update()

    def _start_animation(self):
        """Start animation."""
        if self._animation_timer_id is None:
            self._animation_timer_id = self.startTimer(50)  # 20 FPS

    def _stop_animation(self):
        """Stop animation."""
        if self._animation_timer_id is not None:
            self.killTimer(self._animation_timer_id)
            self._animation_timer_id = None
            self._spin_angle = 0.0
            self._waveform_phase = 0.0

    def timerEvent(self, event):
        """Handle animation timer."""
        self._spin_angle += 8
        if self._spin_angle >= 360:
            self._spin_angle = 0
        self._waveform_phase += 0.2
        if self._waveform_phase > 6.28:
            self._waveform_phase -= 6.28
        self.update()

    def paintEvent(self, event):
        """Draw the button with state-appropriate visuals."""
        super().paintEvent(event)

        if self._state == VoiceButtonState.IDLE:
            self._draw_mic_icon()
        elif self._state == VoiceButtonState.LOADING:
            self._draw_loading_spinner()
        elif self._state == VoiceButtonState.RECORDING:
            self._draw_waveform(animated=True, color="#f44336")  # Red
        elif self._state == VoiceButtonState.PROCESSING:
            self._draw_waveform(animated=False, color="#ff9800")  # Orange

    def _draw_mic_icon(self):
        """Draw a mic icon in the center."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        cx, cy = rect.width() / 2, rect.height() / 2

        # Determine color based on hover state
        color = QColor("#888888")
        if self._theme:
            color = QColor(self._theme.text_secondary)

        pen = QPen(color)
        pen.setWidth(2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # Draw mic body (rounded rectangle)
        mic_width = 8
        mic_height = 12
        mic_x = cx - mic_width / 2
        mic_y = cy - mic_height / 2 - 2
        painter.drawRoundedRect(
            int(mic_x), int(mic_y), int(mic_width), int(mic_height), 4, 4
        )

        # Draw mic stand (arc below)
        arc_rect = rect.adjusted(
            int(cx - 8), int(cy - 2), int(-(cx - 8)), int(-cy + 14)
        )
        painter.drawArc(arc_rect, 0, -180 * 16)

        # Draw mic base (vertical line)
        painter.drawLine(int(cx), int(cy + 10), int(cx), int(cy + 14))

        painter.end()

    def _draw_loading_spinner(self):
        """Draw a spinning arc to indicate loading."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()

        # Draw grayed out mic icon first
        self._draw_mic_icon_internal(painter, QColor("#aaaaaa"))

        # Draw spinning arc on top
        arc_rect = rect.adjusted(4, 4, -4, -4)
        pen = QPen(QColor("#2196f3"))  # Blue spinner
        pen.setWidth(3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        # Draw arc (120 degrees)
        painter.drawArc(arc_rect, int(self._spin_angle * 16), 120 * 16)

        painter.end()

    def _draw_mic_icon_internal(self, painter: QPainter, color: QColor):
        """Draw mic icon with given painter and color."""
        rect = self.rect()
        cx, cy = rect.width() / 2, rect.height() / 2

        pen = QPen(color)
        pen.setWidth(2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # Draw mic body
        mic_width = 8
        mic_height = 12
        mic_x = cx - mic_width / 2
        mic_y = cy - mic_height / 2 - 2
        painter.drawRoundedRect(
            int(mic_x), int(mic_y), int(mic_width), int(mic_height), 4, 4
        )

        # Draw mic stand arc
        arc_rect = rect.adjusted(
            int(cx - 8), int(cy - 2), int(-(cx - 8)), int(-cy + 14)
        )
        painter.drawArc(arc_rect, 0, -180 * 16)

        # Draw mic base line
        painter.drawLine(int(cx), int(cy + 10), int(cx), int(cy + 14))

    def _draw_waveform(self, animated: bool, color: str):
        """Draw waveform bars (like VoiceModeButton)."""
        import math

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        cx = rect.width() / 2
        cy = rect.height() / 2

        bar_width = 3
        bar_spacing = 5
        num_bars = 5
        max_height = rect.height() * 0.5

        pen = QPen(QColor(color))
        pen.setWidth(bar_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        # Draw waveform bars
        total_width = (num_bars - 1) * bar_spacing
        start_x = cx - total_width / 2

        for i in range(num_bars):
            x = start_x + i * bar_spacing

            if animated:
                # Animated wave
                phase_offset = i * 0.8
                h = max_height * (0.3 + 0.5 * abs(math.sin(self._waveform_phase + phase_offset)))
            else:
                # Static wave pattern
                heights = [0.3, 0.6, 0.8, 0.6, 0.3]
                h = max_height * heights[i]

            y1 = cy - h / 2
            y2 = cy + h / 2
            painter.drawLine(int(x), int(y1), int(x), int(y2))

        painter.end()


class VoiceModeButton(QPushButton):
    """White circular button with waveform visualization for voice mode.

    Shows a static waveform icon when idle, animated waveform when active.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._state = VoiceButtonState.IDLE
        self._theme: Optional[Theme] = None
        self._waveform_phase = 0.0
        self._animation_timer_id: Optional[int] = None

        # Default styling (will be overridden by theme)
        self.setStyleSheet("""
            VoiceModeButton {
                background-color: #f0f0f0;
                border: 2px solid #cccccc;
                border-radius: 20px;
            }
            VoiceModeButton:hover {
                background-color: #e0e0e0;
                border-color: #aaaaaa;
            }
        """)

    def set_theme(self, theme: Theme):
        """Apply theme styling."""
        self._theme = theme
        self._update_style()

    def _update_style(self):
        """Update stylesheet based on current state and theme."""
        if not self._theme:
            return

        # Base colors depend on state
        if self._state == VoiceButtonState.IDLE:
            bg = "#ffffff"
            border = self._theme.border
        elif self._state == VoiceButtonState.LOADING:
            bg = "#e3f2fd"  # Light blue
            border = self._theme.accent
        elif self._state == VoiceButtonState.LISTENING:
            bg = "#e8f5e9"  # Light green
            border = "#4caf50"  # Green
        elif self._state == VoiceButtonState.RECORDING:
            bg = "#ffebee"  # Light red
            border = self._theme.error
        elif self._state == VoiceButtonState.PROCESSING:
            bg = "#fff3e0"  # Light orange
            border = self._theme.warning
        elif self._state == VoiceButtonState.SPEAKING:
            bg = "#e3f2fd"  # Light blue
            border = self._theme.accent
        else:
            bg = "#ffffff"
            border = self._theme.border

        self.setStyleSheet(f"""
            VoiceModeButton {{
                background-color: {bg};
                border: 2px solid {border};
                border-radius: 20px;
            }}
            VoiceModeButton:hover {{
                border-color: {self._theme.accent};
            }}
        """)

    def set_state(self, state: str):
        """Set the button state."""
        old_state = self._state
        self._state = state
        self._update_style()

        # Start/stop animation
        is_active = state != VoiceButtonState.IDLE
        was_active = old_state != VoiceButtonState.IDLE

        if is_active and not was_active:
            self._start_animation()
        elif not is_active and was_active:
            self._stop_animation()

        self.update()

    def _start_animation(self):
        """Start waveform animation."""
        if self._animation_timer_id is None:
            self._animation_timer_id = self.startTimer(50)  # 20 FPS

    def _stop_animation(self):
        """Stop waveform animation."""
        if self._animation_timer_id is not None:
            self.killTimer(self._animation_timer_id)
            self._animation_timer_id = None
            self._waveform_phase = 0.0

    def timerEvent(self, event):
        """Handle animation timer."""
        self._waveform_phase += 0.15
        if self._waveform_phase > 6.28:  # 2*pi
            self._waveform_phase -= 6.28
        self.update()

    def paintEvent(self, event):
        """Draw the button with waveform visualization."""
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Calculate center and size
        rect = self.rect()
        cx = rect.width() / 2
        cy = rect.height() / 2
        bar_width = 3
        bar_spacing = 5
        num_bars = 5
        max_height = rect.height() * 0.5

        # Determine bar color based on state
        if self._state == VoiceButtonState.IDLE:
            color = QColor("#888888")
        elif self._state == VoiceButtonState.LISTENING:
            color = QColor("#4caf50")  # Green
        elif self._state == VoiceButtonState.RECORDING:
            color = QColor("#f44336")  # Red
        elif self._state == VoiceButtonState.PROCESSING:
            color = QColor("#ff9800")  # Orange
        elif self._state == VoiceButtonState.SPEAKING:
            color = QColor("#2196f3")  # Blue
        else:
            color = QColor("#888888")

        pen = QPen(color)
        pen.setWidth(bar_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        # Draw waveform bars
        total_width = (num_bars - 1) * bar_spacing
        start_x = cx - total_width / 2

        import math

        for i in range(num_bars):
            x = start_x + i * bar_spacing

            if self._state == VoiceButtonState.IDLE:
                # Static wave pattern
                heights = [0.3, 0.6, 0.8, 0.6, 0.3]
                h = max_height * heights[i]
            else:
                # Animated wave
                phase_offset = i * 0.8
                h = max_height * (0.3 + 0.5 * abs(math.sin(self._waveform_phase + phase_offset)))

            y1 = cy - h / 2
            y2 = cy + h / 2
            painter.drawLine(int(x), int(y1), int(x), int(y2))

        painter.end()


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
    """Input area with text field, send button, mic button, and voice mode button.

    Layout: [Text Input] [Mic (STT)] [Voice Mode] [Send]

    Signals:
        message_submitted(str): Emitted when user submits a message
        mic_clicked: Emitted when mic button is clicked (speech-to-text only)
        voice_mode_clicked: Emitted when voice mode button is clicked (full voice mode)
    """

    message_submitted = Signal(str)
    mic_clicked = Signal()
    voice_mode_clicked = Signal()

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
        self._mic_state = VoiceButtonState.IDLE
        self._voice_mode_state = VoiceButtonState.IDLE
        self._voice_mode_active = False

        self._setup_ui()

    def _setup_ui(self):
        """Set up the input area."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 16)
        layout.setSpacing(8)

        # Text input (first, taking most space)
        self._text_edit = InputTextEdit()
        self._text_edit.setPlaceholderText(self._placeholder)
        self._text_edit.setMinimumHeight(44)
        self._text_edit.setMaximumHeight(150)
        self._text_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        self._text_edit.submit_requested.connect(self._on_submit)
        self._text_edit.textChanged.connect(self._adjust_height)
        layout.addWidget(self._text_edit)

        # Mic button (speech-to-text only) - custom animated button
        self._mic_btn = MicButton()
        self._mic_btn.setObjectName("micButton")
        self._mic_btn.setFixedSize(40, 40)
        self._mic_btn.clicked.connect(self._on_mic_clicked)
        self._mic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self._mic_btn)

        # Voice mode button (white circle with waveform indicator)
        self._voice_mode_btn = VoiceModeButton()
        self._voice_mode_btn.setFixedSize(40, 40)
        self._voice_mode_btn.setToolTip("Start Voice Mode")
        self._voice_mode_btn.clicked.connect(self._on_voice_mode_clicked)
        self._voice_mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self._voice_mode_btn)

        # Send button
        self._send_btn = QPushButton("Send")
        self._send_btn.setObjectName("sendButton")
        self._send_btn.setMinimumWidth(70)
        self._send_btn.setMinimumHeight(40)
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

            /* Send button */
            QPushButton#sendButton {{
                background-color: {self._theme.accent};
                color: white;
                border: none;
                border-radius: 8px;
                font-weight: bold;
                padding: 8px 16px;
            }}

            QPushButton#sendButton:hover {{
                background-color: {self._theme.accent_hover};
            }}

            QPushButton#sendButton:disabled {{
                background-color: {self._theme.bg_tertiary};
                color: {self._theme.text_secondary};
            }}
        """)

        # Update custom button themes
        self._mic_btn.set_theme(self._theme)
        self._voice_mode_btn.set_theme(self._theme)

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
        """Handle mic button click (speech-to-text only)."""
        self.mic_clicked.emit()

    def _on_voice_mode_clicked(self):
        """Handle voice mode button click (full voice mode)."""
        self.voice_mode_clicked.emit()

    def set_mic_state(self, state: str):
        """Set the mic button state.

        Args:
            state: One of VoiceButtonState values (IDLE, LOADING, RECORDING, PROCESSING)
        """
        self._mic_state = state
        self._mic_btn.set_state(state)

    def set_voice_mode_state(self, state: str):
        """Set the voice mode button state.

        Args:
            state: One of VoiceButtonState values
        """
        self._voice_mode_state = state
        self._voice_mode_active = state != VoiceButtonState.IDLE

        # Update button appearance
        self._voice_mode_btn.set_state(state)

        # Update tooltip
        if state == VoiceButtonState.LISTENING:
            self._voice_mode_btn.setToolTip("Listening for wake word... click to stop")
        elif state == VoiceButtonState.RECORDING:
            self._voice_mode_btn.setToolTip("Recording speech...")
        elif state == VoiceButtonState.PROCESSING:
            self._voice_mode_btn.setToolTip("Processing...")
        elif state == VoiceButtonState.SPEAKING:
            self._voice_mode_btn.setToolTip("Speaking... click to stop")
        else:
            self._voice_mode_btn.setToolTip("Start Voice Mode")

    def set_voice_mode_active(self, active: bool):
        """Set whether voice mode is active (convenience method)."""
        if active:
            self.set_voice_mode_state(VoiceButtonState.LISTENING)
        else:
            self.set_voice_mode_state(VoiceButtonState.IDLE)

    def set_mic_visible(self, visible: bool):
        """Show or hide the mic button."""
        self._mic_btn.setVisible(visible)

    def set_mic_enabled(self, enabled: bool):
        """Enable or disable the mic button."""
        self._mic_btn.setEnabled(enabled)

    def set_voice_mode_visible(self, visible: bool):
        """Show or hide the voice mode button."""
        self._voice_mode_btn.setVisible(visible)

    def set_voice_mode_enabled(self, enabled: bool):
        """Enable or disable the voice mode button."""
        self._voice_mode_btn.setEnabled(enabled)

    def is_voice_mode_active(self) -> bool:
        """Check if voice mode is currently active."""
        return self._voice_mode_active
