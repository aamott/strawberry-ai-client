"""Status bar component for GUI V2."""

from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from ..models.state import ConnectionStatus, VoiceStatus
from ..utils.icons import Icons


class StatusBar(QFrame):
    """Application status bar showing connection, device, and voice status.

    Displays:
    - Hub connection status (connected/disconnected/connecting)
    - Device name
    - Voice mode status
    - Application version

    Supports temporary flash messages that auto-dismiss.
    """

    HEIGHT = 28

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._connection_status = ConnectionStatus.DISCONNECTED
        self._device_name = "unknown"
        self._voice_status = VoiceStatus.READY
        # Read version from QApplication metadata; fall back to "0.0.0"
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        self._version = app.applicationVersion() if app else "0.0.0"
        self._flash_timer: Optional[QTimer] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Initialize the UI layout."""
        self.setObjectName("StatusBar")
        self.setFixedHeight(self.HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(16)

        # Connection status
        self._connection_label = QLabel()
        self._connection_label.setObjectName("ConnectionStatus")
        self._connection_label.setToolTip("Hub connection status")
        self._update_connection_label()
        layout.addWidget(self._connection_label)

        # Separator
        layout.addWidget(self._create_separator())

        # Device name
        self._device_label = QLabel()
        self._device_label.setObjectName("DeviceName")
        self._device_label.setToolTip("Current device name")
        self._update_device_label()
        layout.addWidget(self._device_label)

        # Separator
        layout.addWidget(self._create_separator())

        # Voice status
        self._voice_label = QLabel()
        self._voice_label.setObjectName("VoiceStatus")
        self._update_voice_label()
        layout.addWidget(self._voice_label)

        # Stretch
        layout.addStretch()

        # Flash message area (hidden by default)
        self._flash_label = QLabel()
        self._flash_label.setObjectName("FlashMessage")
        self._flash_label.hide()
        layout.addWidget(self._flash_label)

        # Version
        self._version_label = QLabel(f"v{self._version}")
        self._version_label.setObjectName("VersionLabel")
        self._version_label.setToolTip("App version")
        layout.addWidget(self._version_label)

    def _create_separator(self) -> QLabel:
        """Create a vertical separator label."""
        sep = QLabel("│")
        sep.setObjectName("Separator")
        return sep

    def _update_connection_label(self) -> None:
        """Update the connection status display."""
        if self._connection_status == ConnectionStatus.CONNECTED:
            icon = Icons.CONNECTED
            text = "Hub: Connected"
        elif self._connection_status == ConnectionStatus.CONNECTING:
            icon = Icons.CONNECTING
            text = "Hub: Connecting..."
        else:
            icon = Icons.DISCONNECTED
            text = "Hub: Disconnected"

        self._connection_label.setText(f"{icon} {text}")

    def _update_device_label(self) -> None:
        """Update the device name display."""
        self._device_label.setText(f"{Icons.DEVICE} {self._device_name}")

    def _update_voice_label(self) -> None:
        """Update the voice status display."""
        status_map = {
            VoiceStatus.IDLE: (Icons.VOICE_READY, "Voice: Idle"),
            VoiceStatus.READY: (Icons.VOICE_READY, "Voice: Ready"),
            VoiceStatus.STARTING: (Icons.VOICE_PROCESSING, "Voice: Starting..."),
            VoiceStatus.LISTENING: (Icons.VOICE_LISTENING, "Voice: Listening"),
            VoiceStatus.PROCESSING: (Icons.VOICE_PROCESSING, "Voice: Processing"),
            VoiceStatus.SPEAKING: (Icons.VOICE_READY, "Voice: Speaking"),
            VoiceStatus.DISABLED: (Icons.VOICE_DISABLED, "Voice: Unavailable"),
            VoiceStatus.ERROR: (Icons.VOICE_ERROR, "Voice: Error"),
        }
        icon, text = status_map.get(
            self._voice_status, (Icons.VOICE_DISABLED, "Voice: Unknown")
        )
        self._voice_label.setText(f"{icon} {text}")

    def set_connection(self, status: ConnectionStatus, details: Optional[str] = None) -> None:
        """Update the connection status.

        Args:
            status: New connection status
            details: Optional additional details to display
        """
        self._connection_status = status
        self._update_connection_label()
        if details:
            self.flash_message(details, duration=3000)

    def set_device_name(self, name: str) -> None:
        """Update the device name."""
        self._device_name = name
        self._update_device_label()

    def set_voice_status(self, status: VoiceStatus) -> None:
        """Update the voice status."""
        self._voice_status = status
        self._update_voice_label()

    def set_version(self, version: str) -> None:
        """Update the version display."""
        self._version = version
        self._version_label.setText(f"v{version}")

    def flash_message(self, message: str, duration: int = 3000) -> None:
        """Show a temporary message that auto-dismisses.

        Args:
            message: Message to display
            duration: How long to show the message in milliseconds
        """
        # Cancel any existing flash
        if self._flash_timer:
            self._flash_timer.stop()

        self._flash_label.setText(message)
        self._flash_label.show()

        # Set up auto-dismiss timer
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._hide_flash)
        self._flash_timer.start(duration)

    def _hide_flash(self) -> None:
        """Hide the flash message."""
        self._flash_label.hide()
        self._flash_timer = None
