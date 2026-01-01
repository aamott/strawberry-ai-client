"""Voice activity indicator widget."""

from typing import List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from ..theme import Theme


class VoiceLevelBar(QWidget):
    """Animated bar showing audio level."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._level = 0.0
        self._target_level = 0.0
        self._color = QColor("#3fb950")
        self._bg_color = QColor("#30363d")

        self.setFixedSize(4, 24)

        # Smooth animation
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_level)
        self._timer.start(16)  # ~60fps

    def set_level(self, level: float):
        """Set target level (0.0 to 1.0)."""
        self._target_level = max(0.0, min(1.0, level))

    def set_color(self, color: str):
        """Set the bar color."""
        self._color = QColor(color)

    def set_bg_color(self, color: str):
        """Set the background color."""
        self._bg_color = QColor(color)

    def _update_level(self):
        """Smoothly animate toward target level."""
        diff = self._target_level - self._level
        self._level += diff * 0.3  # Smooth interpolation
        self.update()

    def paintEvent(self, event):
        """Paint the bar."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()

        # Background
        painter.setBrush(QBrush(self._bg_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, w, h, 2, 2)

        # Level bar (grows from bottom)
        if self._level > 0.01:
            bar_height = int(h * self._level)
            painter.setBrush(QBrush(self._color))
            painter.drawRoundedRect(0, h - bar_height, w, bar_height, 2, 2)


class VoiceIndicator(QFrame):
    """Voice activity indicator with microphone button and level bars.
    
    Shows:
    - Microphone toggle button
    - Audio level visualization
    - Current state (idle, listening, processing, speaking)
    
    Signals:
        voice_toggled(bool): Emitted when voice mode is toggled
        push_to_talk_pressed: Emitted when PTT button is pressed
        push_to_talk_released: Emitted when PTT button is released
    """

    voice_toggled = Signal(bool)
    push_to_talk_pressed = Signal()
    push_to_talk_released = Signal()

    # States
    STATE_IDLE = "idle"
    STATE_LISTENING = "listening"
    STATE_WAKE_DETECTED = "wake_detected"
    STATE_RECORDING = "recording"
    STATE_PROCESSING = "processing"
    STATE_SPEAKING = "speaking"

    def __init__(
        self,
        theme: Optional[Theme] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        self._theme = theme
        self._voice_enabled = False
        self._state = self.STATE_IDLE
        self._level = 0.0

        self._setup_ui()
        self._apply_theme()

    def _setup_ui(self):
        """Set up the indicator UI."""
        self.setObjectName("voiceIndicator")
        self.setFixedHeight(48)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        # Microphone button
        self._mic_btn = QPushButton("🎤")
        self._mic_btn.setObjectName("micButton")
        self._mic_btn.setFixedSize(32, 32)
        self._mic_btn.setCheckable(True)
        self._mic_btn.clicked.connect(self._on_mic_clicked)
        self._mic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self._mic_btn)

        # Level bars (5 bars for visualization)
        self._bars: List[VoiceLevelBar] = []
        for i in range(5):
            bar = VoiceLevelBar()
            self._bars.append(bar)
            layout.addWidget(bar)

        # State label
        self._state_label = QLabel("Voice Off")
        self._state_label.setProperty("muted", True)
        layout.addWidget(self._state_label)

        layout.addStretch()

        # Push-to-talk button (hold to speak)
        self._ptt_btn = QPushButton("Hold to Speak")
        self._ptt_btn.setObjectName("pttButton")
        self._ptt_btn.setProperty("secondary", True)
        self._ptt_btn.pressed.connect(self.push_to_talk_pressed.emit)
        self._ptt_btn.released.connect(self.push_to_talk_released.emit)
        self._ptt_btn.setVisible(False)  # Hidden by default
        layout.addWidget(self._ptt_btn)

    def _apply_theme(self):
        """Apply theme styling."""
        if not self._theme:
            return

        self.setStyleSheet(f"""
            QFrame#voiceIndicator {{
                background-color: {self._theme.bg_secondary};
                border-bottom: 1px solid {self._theme.border};
            }}
            
            QPushButton#micButton {{
                background-color: {self._theme.bg_tertiary};
                border: none;
                border-radius: 16px;
                font-size: 16px;
            }}
            
            QPushButton#micButton:checked {{
                background-color: {self._theme.accent};
            }}
            
            QPushButton#micButton:hover {{
                background-color: {self._theme.border};
            }}
            
            QPushButton#micButton:checked:hover {{
                background-color: {self._theme.accent_hover};
            }}
        """)

        # Update bar colors
        for bar in self._bars:
            bar.set_bg_color(self._theme.bg_tertiary)
            bar.set_color(self._theme.success)

    def _on_mic_clicked(self, checked: bool):
        """Handle mic button click."""
        self._voice_enabled = checked
        self.voice_toggled.emit(checked)
        self._update_state_display()

    def set_voice_enabled(self, enabled: bool):
        """Set voice mode enabled state."""
        self._voice_enabled = enabled
        self._mic_btn.setChecked(enabled)
        self._update_state_display()

    def set_state(self, state: str):
        """Set the current state."""
        self._state = state
        self._update_state_display()

    def set_level(self, level: float):
        """Set the audio level (0.0 to 1.0)."""
        self._level = level

        # Distribute level across bars with some variation
        for i, bar in enumerate(self._bars):
            # Center bars get more, edges get less
            center = len(self._bars) // 2
            distance = abs(i - center) / center
            bar_level = level * (1.0 - distance * 0.3)

            # Add some randomness for natural look
            import random
            bar_level *= (0.8 + random.random() * 0.4)

            bar.set_level(bar_level)

    def _update_state_display(self):
        """Update the UI based on current state."""
        if not self._voice_enabled:
            self._state_label.setText("Voice Off")
            self.set_level(0)
            return

        state_texts = {
            self.STATE_IDLE: "Listening for wake word...",
            self.STATE_LISTENING: "Listening...",
            self.STATE_WAKE_DETECTED: "Wake word detected!",
            self.STATE_RECORDING: "Recording...",
            self.STATE_PROCESSING: "Processing...",
            self.STATE_SPEAKING: "Speaking...",
        }

        self._state_label.setText(state_texts.get(self._state, "Ready"))

        # Update bar colors based on state
        if self._theme:
            if self._state == self.STATE_RECORDING:
                color = self._theme.error  # Red while recording
            elif self._state == self.STATE_SPEAKING:
                color = self._theme.accent  # Accent while speaking
            elif self._state == self.STATE_WAKE_DETECTED:
                color = self._theme.warning  # Yellow on wake
            else:
                color = self._theme.success  # Green normally

            for bar in self._bars:
                bar.set_color(color)

    def set_ptt_visible(self, visible: bool):
        """Show/hide push-to-talk button."""
        self._ptt_btn.setVisible(visible)

    def set_theme(self, theme: Theme):
        """Update theme."""
        self._theme = theme
        self._apply_theme()

