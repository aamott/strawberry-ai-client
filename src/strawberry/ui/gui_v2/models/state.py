"""UI State models for GUI V2."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ConnectionStatus(Enum):
    """Hub connection status."""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"


class VoiceStatus(Enum):
    """Voice mode status."""
    IDLE = "idle"
    READY = "ready"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass
class UIState:
    """Global UI state container.

    Attributes:
        sidebar_expanded: Whether the sidebar rail is expanded
        current_session_id: Currently active session ID
        connection_status: Hub connection status
        device_name: Current device name
        voice_status: Voice mode status
        is_typing: Whether the assistant is currently typing
        offline_mode: Whether running in offline mode
        settings_panel_open: Whether settings panel is visible
    """
    sidebar_expanded: bool = False
    current_session_id: Optional[str] = None
    connection_status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    device_name: str = "unknown"
    voice_status: VoiceStatus = VoiceStatus.READY
    is_typing: bool = False
    offline_mode: bool = False
    settings_panel_open: bool = False
