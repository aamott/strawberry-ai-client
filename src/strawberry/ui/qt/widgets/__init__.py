"""Custom widgets for Strawberry UI."""

# All widgets require PySide6, so we import them conditionally
# This allows headless unit tests to import specific modules directly
__all__ = []

try:
    from .assistant_turn_widget import AssistantTurnWidget
    from .auto_resizing_text_browser import AutoResizingTextBrowser
    from .chat_area import ChatArea
    from .chat_bubble import ChatBubble
    from .chat_history import ChatHistorySidebar
    from .input_area import InputArea, MicButton, MicState, VoiceButtonState, VoiceModeButton
    from .offline_banner import OfflineModeBanner
    from .rename_dialog import RenameDialog
    from .schema_settings import SchemaSettingsWidget
    from .status_bar import StatusBar
    from .voice_indicator import VoiceIndicator

    __all__ = [
        "AssistantTurnWidget",
        "AutoResizingTextBrowser",
        "ChatArea",
        "ChatBubble",
        "ChatHistorySidebar",
        "InputArea",
        "MicButton",
        "MicState",
        "OfflineModeBanner",
        "RenameDialog",
        "SchemaSettingsWidget",
        "StatusBar",
        "VoiceButtonState",
        "VoiceIndicator",
        "VoiceModeButton",
    ]
except ImportError:
    # PySide6 not available - widgets cannot be imported
    # Individual modules can still be imported directly if they don't require Qt
    pass
