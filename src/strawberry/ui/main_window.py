"""Main application window."""

import asyncio
from typing import Optional, List
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QMenuBar, QMenu, QSplitter, QFrame
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer
from PySide6.QtGui import QAction, QFont, QIcon

from .theme import Theme, THEMES, get_stylesheet, DARK_THEME
from .widgets import ChatArea, InputArea, StatusBar, VoiceIndicator
from .voice_controller import VoiceController
from ..config import Settings
from ..hub import HubClient, HubConfig
from ..hub.client import ChatMessage, HubError


class MainWindow(QMainWindow):
    """Main application window with chat interface.
    
    Signals:
        closing: Emitted when window is about to close
        minimized_to_tray: Emitted when minimized to system tray
    """
    
    closing = Signal()
    minimized_to_tray = Signal()
    
    def __init__(
        self,
        settings: Settings,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        
        self.settings = settings
        self._theme = THEMES.get(settings.ui.theme, DARK_THEME)
        self._hub_client: Optional[HubClient] = None
        self._conversation_history: List[ChatMessage] = []
        self._connected = False
        self._voice_controller: Optional[VoiceController] = None
        
        self._setup_window()
        self._setup_menu()
        self._setup_ui()
        self._apply_theme()
        
        # Initialize Hub connection
        QTimer.singleShot(100, self._init_hub)
    
    def _setup_window(self):
        """Configure the main window."""
        self.setWindowTitle("🍓 Strawberry AI")
        self.setMinimumSize(500, 600)
        self.resize(700, 800)
        
        # Center on screen
        screen = self.screen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)
    
    def _setup_menu(self):
        """Set up the menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        
        new_chat = QAction("&New Chat", self)
        new_chat.setShortcut("Ctrl+N")
        new_chat.triggered.connect(self._on_new_chat)
        file_menu.addAction(new_chat)
        
        file_menu.addSeparator()
        
        settings_action = QAction("&Settings...", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self._on_settings)
        file_menu.addAction(settings_action)
        
        file_menu.addSeparator()
        
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)
        
        # View menu
        view_menu = menubar.addMenu("&View")
        
        theme_menu = view_menu.addMenu("&Theme")
        for theme_name in THEMES:
            action = QAction(theme_name.capitalize(), self)
            action.setCheckable(True)
            action.setChecked(theme_name == self._theme.name)
            action.triggered.connect(lambda checked, t=theme_name: self._set_theme(t))
            theme_menu.addAction(action)
        
        view_menu.addSeparator()
        
        minimize_tray = QAction("Minimize to &Tray", self)
        minimize_tray.setShortcut("Ctrl+H")
        minimize_tray.triggered.connect(self._minimize_to_tray)
        view_menu.addAction(minimize_tray)
        
        # Voice menu
        voice_menu = menubar.addMenu("&Voice")
        
        self._voice_toggle_action = QAction("Enable &Voice Mode", self)
        self._voice_toggle_action.setShortcut("Ctrl+M")
        self._voice_toggle_action.setCheckable(True)
        self._voice_toggle_action.triggered.connect(self._toggle_voice_mode)
        voice_menu.addAction(self._voice_toggle_action)
        
        voice_menu.addSeparator()
        
        voice_settings = QAction("Voice &Settings...", self)
        voice_settings.triggered.connect(self._on_voice_settings)
        voice_menu.addAction(voice_settings)
        
        # Help menu
        help_menu = menubar.addMenu("&Help")
        
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)
    
    def _setup_ui(self):
        """Set up the main UI."""
        central = QWidget()
        self.setCentralWidget(central)
        
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header
        header = self._create_header()
        layout.addWidget(header)
        
        # Voice indicator (hidden by default)
        self._voice_indicator = VoiceIndicator(theme=self._theme)
        self._voice_indicator.setVisible(False)
        self._voice_indicator.voice_toggled.connect(self._on_voice_toggled)
        layout.addWidget(self._voice_indicator)
        
        # Chat area
        self._chat_area = ChatArea(theme=self._theme)
        layout.addWidget(self._chat_area, 1)
        
        # Input area
        self._input_area = InputArea(
            theme=self._theme,
            placeholder="Type your message... (Enter to send, Shift+Enter for newline)",
        )
        self._input_area.message_submitted.connect(self._on_message_submitted)
        layout.addWidget(self._input_area)
        
        # Status bar
        self._status_bar = StatusBar(theme=self._theme)
        layout.addWidget(self._status_bar)
    
    def _create_header(self) -> QWidget:
        """Create the header area."""
        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(60)
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 0, 16, 0)
        
        # Logo/title
        title = QLabel("🍓 Strawberry AI")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setWeight(QFont.Weight.Bold)
        title.setFont(title_font)
        layout.addWidget(title)
        
        layout.addStretch()
        
        # Device name
        device_label = QLabel(self.settings.device.name)
        device_label.setProperty("muted", True)
        layout.addWidget(device_label)
        
        return header
    
    def _apply_theme(self):
        """Apply the current theme."""
        self.setStyleSheet(get_stylesheet(self._theme))
        
        # Update header
        header = self.findChild(QFrame, "header")
        if header:
            header.setStyleSheet(f"""
                QFrame#header {{
                    background-color: {self._theme.bg_secondary};
                    border-bottom: 1px solid {self._theme.border};
                }}
            """)
    
    def _set_theme(self, theme_name: str):
        """Change the application theme."""
        if theme_name in THEMES:
            self._theme = THEMES[theme_name]
            self._apply_theme()
            self._chat_area.set_theme(self._theme)
            self._input_area.set_theme(self._theme)
            self._status_bar.set_theme(self._theme)
            
            # Update menu checkmarks
            view_menu = self.menuBar().findChild(QMenu, "")
            # Note: Would need to properly track actions to update checkmarks
    
    def _init_hub(self):
        """Initialize Hub connection."""
        if self.settings.hub.token:
            config = HubConfig(
                url=self.settings.hub.url,
                token=self.settings.hub.token,
                timeout=self.settings.hub.timeout_seconds,
            )
            self._hub_client = HubClient(config)
            
            # Check connection asynchronously
            asyncio.ensure_future(self._check_hub_connection())
        else:
            self._status_bar.set_status("Hub not configured")
            self._chat_area.add_system_message(
                "Hub token not configured. Set HUB_TOKEN in your .env file."
            )
    
    async def _check_hub_connection(self):
        """Check Hub connection status."""
        if self._hub_client:
            try:
                healthy = await self._hub_client.health()
                self._connected = healthy
                
                if healthy:
                    self._status_bar.set_connected(True, self.settings.hub.url)
                    self._chat_area.add_system_message("Connected to Hub. Ready to chat!")
                else:
                    self._status_bar.set_connected(False)
                    self._chat_area.add_system_message(
                        "Hub is not responding. Check if the server is running."
                    )
            except Exception as e:
                self._connected = False
                self._status_bar.set_connected(False)
                self._chat_area.add_system_message(f"Failed to connect to Hub: {e}")
    
    @Slot(str)
    def _on_message_submitted(self, message: str):
        """Handle user message submission."""
        # Add user message to chat
        self._chat_area.add_message(message, is_user=True)
        
        # Send to Hub
        if self._hub_client and self._connected:
            self._input_area.set_sending(True)
            asyncio.ensure_future(self._send_message(message))
        else:
            self._chat_area.add_system_message("Not connected to Hub")
    
    async def _send_message(self, message: str):
        """Send message to Hub and display response."""
        try:
            # Add to history
            self._conversation_history.append(
                ChatMessage(role="user", content=message)
            )
            
            # Get response
            response = await self._hub_client.chat(
                messages=self._conversation_history,
                temperature=0.7,
            )
            
            # Add response to history and display
            self._conversation_history.append(
                ChatMessage(role="assistant", content=response.content)
            )
            self._chat_area.add_message(response.content, is_user=False)
            
            # Update status
            self._status_bar.set_info(f"Model: {response.model}")
            
        except HubError as e:
            self._chat_area.add_system_message(f"Error: {e}")
        except Exception as e:
            self._chat_area.add_system_message(f"Unexpected error: {e}")
        finally:
            self._input_area.set_sending(False)
            self._input_area.set_focus()
    
    def _on_new_chat(self):
        """Start a new chat (clear history)."""
        self._conversation_history.clear()
        self._chat_area.clear_messages()
        self._chat_area.add_system_message("New conversation started")
        self._input_area.set_focus()
    
    def _toggle_voice_mode(self, enabled: bool):
        """Toggle voice mode on/off."""
        if enabled:
            self._enable_voice()
        else:
            self._disable_voice()
    
    def _on_voice_toggled(self, enabled: bool):
        """Handle voice toggle from indicator widget."""
        self._voice_toggle_action.setChecked(enabled)
        self._toggle_voice_mode(enabled)
    
    def _enable_voice(self):
        """Enable voice interaction."""
        # Show voice indicator
        self._voice_indicator.setVisible(True)
        self._voice_indicator.set_voice_enabled(True)
        
        # Create voice controller if needed
        if self._voice_controller is None:
            self._voice_controller = VoiceController(
                settings=self.settings,
                response_handler=self._handle_voice_transcription,
            )
            
            # Connect signals
            self._voice_controller.state_changed.connect(self._on_voice_state_changed)
            self._voice_controller.level_changed.connect(self._voice_indicator.set_level)
            self._voice_controller.wake_word_detected.connect(self._on_wake_word_detected)
            self._voice_controller.transcription_ready.connect(self._on_transcription_ready)
            self._voice_controller.response_ready.connect(self._on_voice_response)
            self._voice_controller.error_occurred.connect(self._on_voice_error)
        
        # Start voice
        if self._voice_controller.start():
            self._chat_area.add_system_message(
                f"Voice mode enabled. Say '{self.settings.wake_word.keywords[0]}' to activate."
            )
        else:
            self._voice_indicator.setVisible(False)
            self._voice_toggle_action.setChecked(False)
    
    def _disable_voice(self):
        """Disable voice interaction."""
        if self._voice_controller:
            self._voice_controller.stop()
        
        self._voice_indicator.setVisible(False)
        self._voice_indicator.set_voice_enabled(False)
        self._chat_area.add_system_message("Voice mode disabled")
    
    def _handle_voice_transcription(self, text: str) -> str:
        """Handle transcription from voice - get LLM response.
        
        This is called from a background thread, so we use a thread-safe
        approach to get the response from the async Hub client.
        """
        if not self._hub_client or not self._connected:
            return f"Hub not connected. You said: {text}"
        
        # Use a new event loop in this thread for the async call
        import asyncio
        import concurrent.futures
        
        # Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self._get_voice_response_async(text))
            return result
        except Exception as e:
            return f"Error: {e}"
        finally:
            try:
                loop.close()
            except Exception:
                pass
    
    async def _get_voice_response_async(self, text: str) -> str:
        """Get response from Hub for voice transcription (async).
        
        Creates a fresh HTTP client since we're in a different thread/loop.
        """
        import httpx
        
        try:
            # Create a new client for this request (thread-safe)
            async with httpx.AsyncClient(
                base_url=self.settings.hub.url,
                timeout=30.0,
            ) as client:
                # Build message history
                messages = [
                    {"role": m.role, "content": m.content}
                    for m in self._conversation_history
                ]
                messages.append({"role": "user", "content": text})
                
                # Use the correct endpoint: /v1/chat/completions (OpenAI-compatible)
                response = await client.post(
                    "/v1/chat/completions",
                    json={
                        "messages": messages,
                        "temperature": 0.7,
                    },
                    headers={"Authorization": f"Bearer {self.settings.hub.token}"},
                )
                
                if response.status_code == 200:
                    data = response.json()
                    # Parse OpenAI-compatible response format
                    choice = data.get("choices", [{}])[0]
                    response_text = choice.get("message", {}).get("content", "")
                    
                    # Update conversation history (thread-safe - just appending)
                    self._conversation_history.append(ChatMessage(role="user", content=text))
                    self._conversation_history.append(ChatMessage(role="assistant", content=response_text))
                    
                    return response_text
                else:
                    return f"Hub error: {response.status_code}"
                    
        except Exception as e:
            return f"Error: {e}"
    
    @Slot(str)
    def _on_voice_state_changed(self, state: str):
        """Handle voice state changes."""
        self._voice_indicator.set_state(state)
    
    @Slot(str)
    def _on_wake_word_detected(self, keyword: str):
        """Handle wake word detection."""
        self._chat_area.add_system_message(f"Wake word '{keyword}' detected!")
    
    @Slot(str)
    def _on_transcription_ready(self, text: str):
        """Handle transcription completion."""
        self._chat_area.add_message(text, is_user=True)
    
    @Slot(str)
    def _on_voice_response(self, text: str):
        """Handle voice response."""
        self._chat_area.add_message(text, is_user=False)
    
    @Slot(str)
    def _on_voice_error(self, error: str):
        """Handle voice error."""
        self._chat_area.add_system_message(f"Voice error: {error}")
    
    def _on_voice_settings(self):
        """Open voice settings."""
        # TODO: Voice-specific settings dialog
        self._chat_area.add_system_message(
            f"Voice settings:\n"
            f"  Wake words: {', '.join(self.settings.wake_word.keywords)}\n"
            f"  Sensitivity: {self.settings.wake_word.sensitivity}\n"
            f"  STT: {self.settings.stt.backend}\n"
            f"  TTS: {self.settings.tts.backend}"
        )
    
    def _on_settings(self):
        """Open settings dialog."""
        from .settings_dialog import SettingsDialog
        
        dialog = SettingsDialog(
            settings=self.settings,
            theme=self._theme,
            parent=self,
        )
        dialog.settings_changed.connect(self._apply_settings_changes)
        dialog.exec()
    
    def _apply_settings_changes(self, changes: dict):
        """Apply settings changes from dialog."""
        # Update in-memory settings
        if "device" in changes:
            self.settings.device.name = changes["device"].get("name", self.settings.device.name)
        
        if "hub" in changes:
            old_url = self.settings.hub.url
            old_token = self.settings.hub.token
            
            self.settings.hub.url = changes["hub"].get("url", self.settings.hub.url)
            self.settings.hub.token = changes["hub"].get("token", self.settings.hub.token)
            
            # Reconnect if Hub settings changed
            if (self.settings.hub.url != old_url or 
                self.settings.hub.token != old_token):
                self._reconnect_hub()
        
        if "ui" in changes:
            new_theme = changes["ui"].get("theme", self._theme.name)
            if new_theme != self._theme.name:
                self._set_theme(new_theme)
            
            self.settings.ui.start_minimized = changes["ui"].get(
                "start_minimized", self.settings.ui.start_minimized
            )
        
        self._chat_area.add_system_message("Settings updated")
    
    def _reconnect_hub(self):
        """Reconnect to Hub with new settings."""
        # Close existing client
        if self._hub_client:
            asyncio.ensure_future(self._hub_client.close())
            self._hub_client = None
        
        self._connected = False
        self._status_bar.set_connected(False)
        
        # Reinitialize
        QTimer.singleShot(100, self._init_hub)
    
    def _on_about(self):
        """Show about dialog."""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.about(
            self,
            "About Strawberry AI",
            "🍓 Strawberry AI Spoke\n\n"
            "Version 0.1.0\n\n"
            "A voice assistant platform using a hub-and-spoke architecture."
        )
    
    def _minimize_to_tray(self):
        """Minimize window to system tray."""
        self.hide()
        self.minimized_to_tray.emit()
    
    def closeEvent(self, event):
        """Handle window close."""
        self.closing.emit()
        
        # Cleanup voice
        if self._voice_controller:
            self._voice_controller.stop()
        
        # Cleanup Hub client
        if self._hub_client:
            asyncio.ensure_future(self._hub_client.close())
        
        event.accept()
    
    def show_and_activate(self):
        """Show window and bring to front."""
        self.show()
        self.raise_()
        self.activateWindow()
        self._input_area.set_focus()

