"""Main application window for GUI V2."""

import asyncio
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
from .models.state import ConnectionStatus, MessageSource, UIState, VoiceStatus
from .services.voice_service import VoiceService
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
        message_submitted: Emitted when user submits a message (str: content, str: source)
        session_changed: Emitted when session changes (str: session_id)
    """

    closing = Signal()
    message_submitted = Signal(str, str)  # content, source (MessageSource value)
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

        # Voice service bridges VoiceCore ↔ Qt signals
        self._voice_service = VoiceService(voice_core=voice_core, parent=self)

        self._setup_window()
        self._setup_ui()
        self._connect_signals()
        self._connect_voice_signals()
        self._apply_theme()
        self._init_voice_state()

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
        """Handle message submission from chat view (typed input)."""
        self.submit_message(content, MessageSource.TYPED)

    def submit_message(
        self, content: str, source: MessageSource = MessageSource.TYPED
    ) -> None:
        """Display a user message and emit message_submitted.

        This is the single entry point for all message submissions
        (typed, voice record, voice mode). It creates the user bubble,
        shows the typing indicator, and signals IntegratedApp.

        Args:
            content: Message text.
            source: How the message was produced (typed, voice_record, voice_mode).
        """
        logger.debug(f"Message sent ({source.value}): {content[:50]}...")

        # Create and display user message
        user_msg = Message(
            id=str(uuid4()),
            role=MessageRole.USER,
            timestamp=datetime.now(),
            segments=[TextSegment(content=content)],
        )
        self._chat_view.add_message(user_msg)

        # Emit signal for external handling (content + source)
        self.message_submitted.emit(content, source.value)

        # Show typing indicator
        self._chat_view.set_typing(True)

        # Disable input while processing
        self._chat_view.set_input_enabled(False)

    # -------------------------------------------------------------------------
    # Voice integration
    # -------------------------------------------------------------------------

    def _init_voice_state(self) -> None:
        """Set initial voice UI state based on VoiceCore availability."""
        available = self._voice_service.is_available
        self._chat_view.set_voice_available(available)
        if available:
            self.set_voice_status(VoiceStatus.IDLE)
        else:
            self.set_voice_status(VoiceStatus.DISABLED)
            logger.info("VoiceCore not provided — voice buttons disabled")

    def _connect_voice_signals(self) -> None:
        """Connect voice-related signals between ChatView and VoiceService."""
        # Record button: tap → trigger_wakeword, hold → PTT
        self._chat_view.record_tapped.connect(self._on_record_tapped)
        self._chat_view.record_hold_start.connect(self._on_record_hold_start)
        self._chat_view.record_hold_stop.connect(self._on_record_hold_stop)

        # Voice mode toggle
        self._chat_view.voice_mode_toggled.connect(self._on_voice_mode_toggled)

        # VoiceService → UI feedback
        self._voice_service.starting.connect(self._on_voice_starting)
        self._voice_service.state_changed.connect(self._on_voice_state_changed)
        self._voice_service.listening_started.connect(self._on_voice_listening)
        self._voice_service.error_occurred.connect(self._on_voice_error)
        self._voice_service.voice_mode_changed.connect(self._on_voice_mode_changed)
        self._voice_service.availability_changed.connect(self._on_voice_availability_changed)

    def _on_record_tapped(self) -> None:
        """Handle record button tap → trigger immediate recording."""
        if not self._voice_service.is_available:
            # Should not happen (buttons are disabled), but guard anyway
            self._voice_service.error_occurred.emit("Voice engine not initialized")
            return
        logger.debug("Record tapped (trigger_wakeword)")
        # Don't set recording state here — _on_voice_state_changed will
        # update the UI once VoiceCore actually transitions to LISTENING.
        asyncio.ensure_future(self._voice_service.trigger_wakeword())

    def _on_record_hold_start(self) -> None:
        """Handle record button hold start → push-to-talk."""
        if not self._voice_service.is_available:
            self._voice_service.error_occurred.emit("Voice engine not initialized")
            return
        logger.debug("Record hold start (PTT)")
        asyncio.ensure_future(self._voice_service.push_to_talk_start())

    def _on_record_hold_stop(self) -> None:
        """Handle record button hold release → stop PTT."""
        logger.debug("Record hold stop (PTT release)")
        self._voice_service.push_to_talk_stop()
        self._chat_view.set_recording_state(False)

    def _on_voice_mode_toggled(self, enabled: bool) -> None:
        """Handle voice mode toggle from UI."""
        logger.debug(f"Voice mode toggled: {enabled}")
        asyncio.ensure_future(self._voice_service.toggle_voice_mode(enabled))

    def _on_voice_starting(self) -> None:
        """Handle VoiceCore starting → show 'Starting...' in status bar."""
        self.set_voice_status(VoiceStatus.STARTING)
        self._status_bar.flash_message("Starting voice engine...", duration=10000)

    def _on_voice_state_changed(self, old_state: str, new_state: str) -> None:
        """Handle VoiceCore state changes → update UI."""
        logger.debug(f"Voice state: {old_state} → {new_state}")

        # Update recording button state
        is_listening = new_state == "LISTENING"
        self._chat_view.set_recording_state(is_listening)

        # Update status bar voice indicator
        status_map = {
            "IDLE": VoiceStatus.READY,
            "LISTENING": VoiceStatus.LISTENING,
            "PROCESSING": VoiceStatus.PROCESSING,
            "SPEAKING": VoiceStatus.SPEAKING,
            "STOPPED": VoiceStatus.DISABLED,
        }
        status = status_map.get(new_state, VoiceStatus.READY)
        self.set_voice_status(status)

    def _on_voice_listening(self) -> None:
        """Handle voice listening started."""
        self._chat_view.set_recording_state(True)

    def _on_voice_error(self, error_msg: str) -> None:
        """Handle voice error → flash a visible message and update status."""
        logger.error(f"Voice error: {error_msg}")
        self._status_bar.flash_message(f"⚠️ {error_msg}", duration=5000)
        self._chat_view.set_recording_state(False)
        self.set_voice_status(VoiceStatus.ERROR)

    def _on_voice_mode_changed(self, active: bool) -> None:
        """Handle voice mode state change from VoiceService → sync UI button."""
        self._chat_view.set_voice_mode(active)
        if active:
            self._status_bar.flash_message("Voice mode: listening for wake word")
            self.set_voice_status(VoiceStatus.READY)
        else:
            self._status_bar.flash_message("Voice mode off")
            self.set_voice_status(VoiceStatus.IDLE)

    def _on_voice_availability_changed(self, available: bool) -> None:
        """Handle VoiceCore being set or cleared at runtime."""
        self._chat_view.set_voice_available(available)
        if available:
            self.set_voice_status(VoiceStatus.IDLE)
            logger.info("VoiceCore now available — voice buttons enabled")
        else:
            self.set_voice_status(VoiceStatus.DISABLED)
            logger.info("VoiceCore removed — voice buttons disabled")

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
    def status_bar(self) -> StatusBar:
        """Get the status bar component."""
        return self._status_bar

    @property
    def voice_service(self) -> VoiceService:
        """Get the voice service instance."""
        return self._voice_service

    @property
    def state(self) -> UIState:
        """Get the current UI state."""
        return self._state

    def closeEvent(self, event) -> None:
        """Handle window close event."""
        self.closing.emit()
        super().closeEvent(event)
