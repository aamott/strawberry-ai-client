"""Main application window for GUI V2."""

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from .components import (
    ChatView,
    MessageCard,
    SidebarRail,
    StatusBar,
    TitleBar,
)
from .models.message import Message, MessageRole, TextSegment
from .models.state import ConnectionStatus, UIState, VoiceStatus
from .themes import DARK_THEME, LIGHT_THEME

if TYPE_CHECKING:
    from ...shared.settings import SettingsManager
    from ...voice import VoiceCore

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window with chat interface.

    Provides a frameless window with custom title bar, collapsible sidebar,
    chat view, and status bar. Coordinates between UI components and
    backend services.

    Signals:
        closing: Emitted when window is about to close
        message_submitted: Emitted when user submits a message (str: content)
        session_changed: Emitted when session changes (str: session_id)
    """

    closing = Signal()
    message_submitted = Signal(str)
    session_changed = Signal(str)

    # Default window size
    DEFAULT_WIDTH = 1000
    DEFAULT_HEIGHT = 700
    MIN_WIDTH = 600
    MIN_HEIGHT = 400

    def __init__(
        self,
        settings_manager: Optional["SettingsManager"] = None,
        voice_core: Optional["VoiceCore"] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        self._settings_manager = settings_manager
        self._voice_core = voice_core
        self._state = UIState()
        self._theme = DARK_THEME

        self._setup_window()
        self._setup_ui()
        self._connect_signals()
        self._apply_theme()

        # Focus input on start
        QTimer.singleShot(100, self._chat_view.focus_input)

    def _setup_window(self) -> None:
        """Configure the main window."""
        self.setWindowTitle("Strawberry AI")
        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)

        # Frameless window with custom title bar
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Window
        )

        # Enable window shadow on supported platforms
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

    def _setup_ui(self) -> None:
        """Initialize the UI layout."""
        # Central widget
        central = QWidget()
        central.setObjectName("CentralWidget")
        self.setCentralWidget(central)

        # Main layout
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Title bar
        self._title_bar = TitleBar(title="Strawberry AI")
        main_layout.addWidget(self._title_bar)

        # Content area (sidebar + chat)
        content = QWidget()
        content.setObjectName("ContentArea")
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Sidebar rail
        self._sidebar = SidebarRail()
        content_layout.addWidget(self._sidebar)

        # Chat view
        self._chat_view = ChatView()
        content_layout.addWidget(self._chat_view, 1)

        main_layout.addWidget(content, 1)

        # Status bar
        self._status_bar = StatusBar()
        main_layout.addWidget(self._status_bar)

    def _connect_signals(self) -> None:
        """Connect component signals."""
        # Title bar
        self._title_bar.menu_clicked.connect(self._on_menu_clicked)
        self._title_bar.minimize_clicked.connect(self.showMinimized)
        self._title_bar.maximize_clicked.connect(self._toggle_maximize)
        self._title_bar.close_clicked.connect(self.close)

        # Sidebar
        self._sidebar.navigation_changed.connect(self._on_navigation_changed)
        self._sidebar.session_selected.connect(self._on_session_selected)
        self._sidebar.new_chat_requested.connect(self._on_new_chat)

        # Chat view
        self._chat_view.message_sent.connect(self._on_message_sent)
        self._chat_view.voice_requested.connect(self._on_voice_requested)

    def _apply_theme(self) -> None:
        """Apply the current theme stylesheet."""
        stylesheet = self._theme.get_stylesheet()
        self.setStyleSheet(stylesheet)

    def _toggle_maximize(self) -> None:
        """Toggle between maximized and normal window state."""
        if self.isMaximized():
            self.showNormal()
            self._title_bar.set_maximized(False)
        else:
            self.showMaximized()
            self._title_bar.set_maximized(True)

    def _on_menu_clicked(self) -> None:
        """Handle menu button click."""
        self._sidebar.toggle()

    def _on_navigation_changed(self, nav_id: str) -> None:
        """Handle navigation item selection.

        Args:
            nav_id: Navigation item identifier
        """
        logger.debug(f"Navigation changed to: {nav_id}")

        if nav_id == "settings":
            self._open_settings()
        elif nav_id == "skills":
            # TODO: Open skills panel
            self._status_bar.flash_message("Skills panel coming soon")

    def _open_settings(self) -> None:
        """Open the settings window."""
        if not self._settings_manager:
            self._status_bar.flash_message("Settings not available")
            return

        from .components import SettingsWindow

        dialog = SettingsWindow(self._settings_manager, self)
        dialog.settings_saved.connect(
            lambda: self._status_bar.flash_message("Settings saved")
        )
        dialog.exec()

    def _on_session_selected(self, session_id: str) -> None:
        """Handle session selection.

        Args:
            session_id: Selected session ID
        """
        logger.debug(f"Session selected: {session_id}")
        self._state.current_session_id = session_id
        self.session_changed.emit(session_id)

        # Collapse sidebar after selection
        self._sidebar.collapse()

    def _on_new_chat(self) -> None:
        """Handle new chat request."""
        logger.debug("New chat requested")

        # Clear current chat
        self._chat_view.clear_messages()

        # Create new session ID
        session_id = str(uuid4())
        self._state.current_session_id = session_id

        # Add to sidebar
        self._sidebar.add_session(session_id, "New Chat")
        self._sidebar.highlight_session(session_id)

        # Collapse sidebar
        self._sidebar.collapse()

        # Focus input
        self._chat_view.focus_input()

    def _on_message_sent(self, content: str) -> None:
        """Handle message submission from chat view.

        Args:
            content: Message content
        """
        logger.debug(f"Message sent: {content[:50]}...")

        # Create and display user message
        user_msg = Message(
            id=str(uuid4()),
            role=MessageRole.USER,
            timestamp=datetime.now(),
            segments=[TextSegment(content=content)],
        )
        self._chat_view.add_message(user_msg)

        # Emit signal for external handling
        self.message_submitted.emit(content)

        # Show typing indicator
        self._chat_view.set_typing(True)

        # Disable input while processing
        self._chat_view.set_input_enabled(False)

    def _on_voice_requested(self) -> None:
        """Handle voice button click."""
        logger.debug("Voice requested")
        # TODO: Integrate with VoiceCore
        self._status_bar.flash_message("Voice input coming soon")

    # Public API for external integration

    def add_assistant_message(self, message_id: Optional[str] = None) -> MessageCard:
        """Add a new assistant message and return the card for streaming.

        Args:
            message_id: Optional message ID (generated if not provided)

        Returns:
            The MessageCard widget for streaming updates
        """
        msg = Message(
            id=message_id or str(uuid4()),
            role=MessageRole.ASSISTANT,
            timestamp=datetime.now(),
            is_streaming=True,
        )
        card = self._chat_view.chat_area.add_message(msg)
        return card

    def finish_assistant_message(self, message_id: str) -> None:
        """Mark an assistant message as finished streaming.

        Args:
            message_id: Message ID to finish
        """
        card = self._chat_view.get_message_card(message_id)
        if card:
            card.set_streaming(False)

        self._chat_view.set_typing(False)
        self._chat_view.set_input_enabled(True)
        self._chat_view.focus_input()

    def set_connection_status(
        self, status: ConnectionStatus, details: Optional[str] = None
    ) -> None:
        """Update the connection status display.

        Args:
            status: New connection status
            details: Optional details to flash
        """
        self._state.connection_status = status
        self._status_bar.set_connection(status, details)

    def set_device_name(self, name: str) -> None:
        """Update the device name display.

        Args:
            name: Device name
        """
        self._state.device_name = name
        self._status_bar.set_device_name(name)

    def set_voice_status(self, status: VoiceStatus) -> None:
        """Update the voice status display.

        Args:
            status: Voice status
        """
        self._state.voice_status = status
        self._status_bar.set_voice_status(status)

    def set_offline_mode(self, offline: bool) -> None:
        """Show or hide the offline mode banner.

        Args:
            offline: Whether running in offline mode
        """
        self._state.offline_mode = offline
        self._chat_view.set_offline_mode(offline)

    def set_sessions(self, sessions: list) -> None:
        """Update the session list in the sidebar.

        Args:
            sessions: List of session dicts with 'id' and 'title' keys
        """
        self._sidebar.set_sessions(sessions)

    def set_theme(self, theme_name: str) -> None:
        """Switch to a different theme.

        Args:
            theme_name: Theme name ('dark' or 'light')
        """
        if theme_name == "light":
            self._theme = LIGHT_THEME
        else:
            self._theme = DARK_THEME
        self._apply_theme()

    @property
    def chat_view(self) -> ChatView:
        """Get the chat view component."""
        return self._chat_view

    @property
    def sidebar(self) -> SidebarRail:
        """Get the sidebar component."""
        return self._sidebar

    @property
    def state(self) -> UIState:
        """Get the current UI state."""
        return self._state

    def closeEvent(self, event) -> None:
        """Handle window close event."""
        self.closing.emit()
        super().closeEvent(event)
