"""Main application window."""

import asyncio
import logging
import os
import traceback
from pathlib import Path
from typing import List, Optional

import httpx
from PySide6.QtCore import QTimer, Signal, Slot
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMainWindow, QVBoxLayout, QWidget

try:
    # Python 3.11+
    BaseExceptionGroup  # type: ignore[name-defined]
except NameError:  # pragma: no cover
    # Python <3.11 (dependency of anyio/httpx in some environments)
    from exceptiongroup import BaseExceptionGroup  # type: ignore[assignment]

from ..config import Settings
from ..config.persistence import persist_settings_and_env
from ..hub import HubClient, HubConfig
from ..hub.client import HubError
from ..llm import OfflineModeTracker, TensorZeroClient
from ..models import ChatMessage
from ..skills import SkillService
from ..storage import LocalSessionDB, SyncManager
from .theme import DARK_THEME, THEMES, get_stylesheet
from .voice_controller import VoiceController
from .widgets import (
    ChatArea,
    ChatHistorySidebar,
    InputArea,
    MicState,
    OfflineModeBanner,
    StatusBar,
    VoiceIndicator,
)

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window with chat interface.

    Signals:
        closing: Emitted when window is about to close
        minimized_to_tray: Emitted when minimized to system tray
    """

    closing = Signal()
    minimized_to_tray = Signal()
    hub_connection_changed = Signal(bool)

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
        self._skill_service: Optional[SkillService] = None
        self._current_session_id: Optional[str] = None

        # Offline mode components
        self._tensorzero_client: Optional[TensorZeroClient] = None
        self._offline_tracker = OfflineModeTracker()
        self._session_db: Optional[LocalSessionDB] = None
        self._sync_manager: Optional[SyncManager] = None

        self._setup_window()
        self._setup_menu()
        self._setup_ui()
        self._apply_theme()

        # Connect signals
        self.hub_connection_changed.connect(self._update_hub_status)

        # Initialize offline mode components
        self._init_local_storage()
        self._init_tensorzero()

        # Connect offline mode listener
        self._offline_tracker.add_listener(self._on_offline_mode_changed)

        # Initialize skills and Hub connection
        self._init_skills()
        QTimer.singleShot(100, self._init_hub)

    def _setup_window(self):
        """Configure the main window."""
        self.setWindowTitle(" Strawberry AI")
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

        # Audio feedback toggle
        self._audio_feedback_action = QAction("&Audio Feedback", self)
        self._audio_feedback_action.setCheckable(True)
        self._audio_feedback_action.setChecked(self.settings.voice.audio_feedback_enabled)
        self._audio_feedback_action.triggered.connect(self._toggle_audio_feedback)
        voice_menu.addAction(self._audio_feedback_action)

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

        # Main horizontal layout (sidebar + content)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Chat history sidebar
        self._chat_sidebar = ChatHistorySidebar(theme=self._theme)
        self._chat_sidebar.session_selected.connect(self._on_session_selected)
        self._chat_sidebar.new_chat_requested.connect(self._on_new_chat)
        self._chat_sidebar.session_deleted.connect(self._on_session_deleted)
        main_layout.addWidget(self._chat_sidebar)

        # Content area (right side)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = self._create_header()
        layout.addWidget(header)

        # Offline mode banner (hidden by default)
        self._offline_banner = OfflineModeBanner(theme=self._theme)
        self._offline_banner.sync_requested.connect(self._on_sync_requested)
        layout.addWidget(self._offline_banner)

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
        self._input_area.mic_clicked.connect(self._on_mic_button_clicked)
        layout.addWidget(self._input_area)

        # Status bar
        self._status_bar = StatusBar(theme=self._theme)
        layout.addWidget(self._status_bar)

        main_layout.addWidget(content, 1)

    def _create_header(self) -> QWidget:
        """Create the header area."""
        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(60)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 0, 16, 0)

        # Logo/title
        title = QLabel(" Strawberry AI")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setWeight(QFont.Weight.Bold)
        title.setFont(title_font)
        title.setFont(title_font)
        layout.addWidget(title)

        layout.addSpacing(12)

        # Status indicator
        self._status_indicator = QLabel()
        self._status_indicator.setFixedSize(12, 12)
        self._status_indicator.setToolTip("Hub Status: Disconnected")
        self._update_indicator_style(False)
        layout.addWidget(self._status_indicator)

        # Status text
        self._status_text = QLabel("Offline")
        self._status_text.setProperty("muted", True)
        layout.addWidget(self._status_text)

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

            # Note: Would need to properly track actions to update checkmarks

    def _init_skills(self):
        """Initialize skill service."""
        skills_path = Path(self.settings.skills.path)

        # Make path absolute if relative
        if not skills_path.is_absolute():
            # Relative to config file or cwd
            skills_path = Path.cwd() / skills_path

        self._skill_service = SkillService(skills_path, device_name=self.settings.device.name)

        # Load skills
        skills = self._skill_service.load_skills()

        if skills:
            skill_names = [s.name for s in skills]
            self._chat_area.add_system_message(
                f"Loaded {len(skills)} skill(s): {', '.join(skill_names)}"
            )
        else:
            self._chat_area.add_system_message(
                f"No skills found in {skills_path}"
            )

    def _init_local_storage(self):
        """Initialize local session storage and sync manager."""
        db_path = Path(self.settings.storage.db_path)
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path

        self._session_db = LocalSessionDB(db_path)
        self._sync_manager = SyncManager(self._session_db, self._hub_client)

    def _init_tensorzero(self):
        """Initialize TensorZero client for LLM routing."""
        if self.settings.tensorzero.enabled:
            # Embedded gateway uses config file, no URL/timeout needed
            self._tensorzero_client = TensorZeroClient()

    def _on_offline_mode_changed(self, is_offline: bool):
        """Handle offline mode state change.

        Args:
            is_offline: True if now in offline mode
        """
        if is_offline:
            pending_count = self._sync_manager.get_pending_count() if self._sync_manager else 0
            self._offline_banner.set_offline(
                model_name=self.settings.local_llm.model,
                pending_count=pending_count,
            )
            self._status_bar.set_status(
                self._offline_tracker.get_status_text(self.settings.local_llm.model)
            )
        else:
            self._offline_banner.set_online()
            self._status_bar.set_connected(True, self.settings.hub.url)
            # Trigger sync when coming back online
            if self._sync_manager:
                asyncio.ensure_future(self._sync_manager.sync_all())

    def _on_sync_requested(self):
        """Handle manual sync request from offline banner."""
        if self._sync_manager:
            self._offline_banner.set_syncing(True)
            asyncio.ensure_future(self._do_manual_sync())

    async def _do_manual_sync(self):
        """Perform manual sync and update UI."""
        try:
            if self._sync_manager:
                success = await self._sync_manager.sync_all()
                if success:
                    self._chat_area.add_system_message("Sync completed successfully")
                    # Update pending count
                    pending = self._sync_manager.get_pending_count()
                    self._offline_banner.update_pending_count(pending)
                    self._offline_tracker.pending_sync_count = pending
                else:
                    self._chat_area.add_system_message("Sync failed - Hub not available")
        except Exception as e:
            self._chat_area.add_system_message(f"Sync error: {e}")
        finally:
            self._offline_banner.set_syncing(False)

    def _init_hub(self):
        """Initialize Hub connection."""
        if self.settings.hub.token:
            config = HubConfig(
                url=self.settings.hub.url,
                token=self.settings.hub.token,
                timeout=self.settings.hub.timeout_seconds,
            )
            self._hub_client = HubClient(config)

            # Update sync manager with hub client
            if self._sync_manager:
                self._sync_manager.set_hub_client(self._hub_client)

            # Set connection callback
            self._hub_client.set_connection_callback(self._on_hub_connection_callback)

            # Check connection asynchronously
            asyncio.ensure_future(self._check_hub_connection())
        else:
            self._status_bar.set_status("Hub not configured")
            self._chat_area.add_system_message(
                "Hub token not configured. Set HUB_DEVICE_TOKEN in your .env file."
            )

    async def _check_hub_connection(self):
        """Check Hub connection status."""
        if self._hub_client:
            try:
                healthy = await self._hub_client.health()
                self._connected = healthy

                if healthy:
                    # Update status manually since callback might not have fired yet if we didn't
                    # use connect_websocket explicitly here
                    # But connect_websocket is called by app logic usually?
                    # Actually HubClient.health() is HTTP, not WebSocket.
                    # We should probably initialize WebSocket here or rely on explicit connect.
                    # For now, let's trust the health check for initial status.
                    self._update_hub_status(True)
                    self._chat_area.add_system_message("Connected to Hub. Ready to chat!")

                    # Connect WebSocket
                    asyncio.create_task(self._hub_client.connect_websocket())

                    # Register skills with Hub
                    await self._register_skills_with_hub()
                else:
                    self._update_hub_status(False)
                    self._chat_area.add_system_message(
                        "Hub is not responding. Check if the server is running."
                    )
            except Exception as e:
                self._update_hub_status(False)

                logger.exception("Failed to connect to Hub")
                err_summary = self._format_exception_for_user(e)
                self._chat_area.add_system_message(
                    f"Failed to connect to Hub: {err_summary}"
                )

    @staticmethod
    def _format_exception_for_user(exc: BaseException) -> str:
        """Format exceptions for display.

        Python 3.11+ can wrap async errors into ExceptionGroup (e.g., from TaskGroup).
        We unwrap those so the user sees the underlying root cause.
        """

        if isinstance(exc, BaseExceptionGroup):
            parts: List[str] = []
            for sub in exc.exceptions:  # type: ignore[attr-defined]
                parts.append(MainWindow._format_exception_for_user(sub))
            return "; ".join(p for p in parts if p) or repr(exc)

        msg = str(exc).strip()
        if not msg:
            msg = repr(exc)
        return f"{type(exc).__name__}: {msg}"

    async def _on_hub_connection_callback(self, connected: bool):
        """Handle Hub connection callback (async)."""
        self.hub_connection_changed.emit(connected)

    @Slot(bool)
    def _update_hub_status(self, connected: bool):
        """Update Hub connection status UI."""
        self._connected = connected

        # Update indicator
        self._update_indicator_style(connected)
        status = "Connected" if connected else "Disconnected"
        self._status_indicator.setToolTip(f"Hub Status: {status}")
        self._status_text.setText("Online" if connected else "Offline")

        # Update status bar
        self._status_bar.set_connected(connected, self.settings.hub.url if connected else None)

        # Refresh sessions when connected
        if connected:
            asyncio.ensure_future(self._refresh_sessions())

    def _update_indicator_style(self, connected: bool):
        """Update indicator style sheet."""
        color = "#4caf50" if connected else "#f44336"  # Green or Red
        self._status_indicator.setStyleSheet(f"""
            background-color: {color};
            border-radius: 6px;
            border: 1px solid {self._theme.border};
        """)

    async def _register_skills_with_hub(self):
        """Register skills with Hub and start heartbeat."""
        if not self._skill_service or not self._hub_client:
            return

        # Set hub client on skill service
        self._skill_service.hub_client = self._hub_client

        # Register skills
        success = await self._skill_service.register_with_hub()

        if success:
            skills = self._skill_service.get_all_skills()
            if skills:
                self._chat_area.add_system_message(
                    f"Registered {len(skills)} skill(s) with Hub"
                )
                # Start heartbeat
                await self._skill_service.start_heartbeat()

                # Notify that remote skills are now available
                self._chat_area.add_system_message(
                    "Remote skills from connected devices are now available. "
                    "Use search_skills() to discover them."
                )
        else:
            self._chat_area.add_system_message(
                "Failed to register skills with Hub (running in local mode)"
            )

    @Slot(str)
    def _on_message_submitted(self, message: str):
        """Handle user message submission."""
        # Add user message to chat
        self._chat_area.add_message(message, is_user=True)

        # Store message locally first
        if self._session_db and self._current_session_id:
            msg = self._session_db.add_message(self._current_session_id, "user", message)
            # Queue for sync
            if self._sync_manager:
                asyncio.ensure_future(
                    self._sync_manager.queue_add_message(
                        self._current_session_id, msg.id, "user", message
                    )
                )
            # Refresh session list to update message count
            asyncio.ensure_future(self._refresh_sessions())

        # Send via TensorZero (handles Hub/local fallback) or direct Hub
        if self._tensorzero_client:
            self._input_area.set_sending(True)
            asyncio.ensure_future(self._send_message_via_tensorzero(message))
        elif self._hub_client and self._connected:
            self._input_area.set_sending(True)
            asyncio.ensure_future(self._send_message(message))
        else:
            self._chat_area.add_system_message(
                "No LLM available. Configure TensorZero or Hub connection."
            )

    async def _send_message(self, message: str):
        """Send message to Hub using agent loop.

        The agent loop allows the LLM to:
        1. Search for skills
        2. Call skills and see results
        3. Continue reasoning based on results
        4. Make more calls or provide final response

        Loop ends when LLM responds without code blocks (max 5 iterations).
        """
        MAX_ITERATIONS = 5

        try:
            assistant_turn = self._chat_area.add_assistant_turn("(Thinking...)")

            # Build initial messages with system prompt
            messages_to_send = []

            # Add system prompt with skills
            if self._skill_service:
                system_prompt = self._skill_service.get_system_prompt()
                messages_to_send.append(ChatMessage(role="system", content=system_prompt))

            # Add conversation history
            messages_to_send.extend(self._conversation_history)

            # Add current message
            messages_to_send.append(ChatMessage(role="user", content=message))

            # Add to local history
            self._conversation_history.append(
                ChatMessage(role="user", content=message)
            )

            # Trim history to prevent unbounded memory growth
            self._trim_history()

            # Agent loop
            all_tool_calls = []
            final_response = None

            for iteration in range(MAX_ITERATIONS):
                print(f"[Agent] Iteration {iteration + 1}/{MAX_ITERATIONS}")

                # Get response from LLM (use configurable temperature)
                response = await self._hub_client.chat(
                    messages=messages_to_send,
                    temperature=self.settings.llm.temperature,
                )

                print(f"[Agent] LLM response: {response.content[:200]}...")

                # Parse for code blocks
                if self._skill_service:
                    code_blocks = self._skill_service.parse_skill_calls(response.content)
                else:
                    code_blocks = []

                print(f"[Agent] Found {len(code_blocks)} code blocks")

                if not code_blocks:
                    # No code blocks = agent is done
                    final_response = response
                    print("[Agent] No code blocks, ending loop")
                    break

                # Phase 1: Show raw output (don't strip code blocks)
                iteration_display = response.content
                if not iteration_display:
                    iteration_display = "(Running tools...)"
                if iteration == 0 and assistant_turn is not None:
                    assistant_turn.set_markdown(
                        f"**Step {iteration + 1}:**\n\n{iteration_display}"
                    )
                else:
                    assistant_turn.append_markdown(
                        f"**Step {iteration + 1}:**\n\n{iteration_display}"
                    )

                # Execute code blocks and display in UI
                outputs = []
                for code in code_blocks:
                    result = await self._skill_service.execute_code_async(code)

                    # Track tool call
                    tool_call_info = {
                        "iteration": iteration + 1,
                        "code": code,
                        "success": result.success,
                        "result": result.result,
                        "error": result.error,
                    }
                    all_tool_calls.append(tool_call_info)

                    # Display in UI (Integrated Notebook Style)
                    if result.success:
                        output_text = result.result or "(no output)"
                        assistant_turn.append_markdown(f"```output\n{output_text}\n```")
                    else:
                        error_text = result.error
                        assistant_turn.append_markdown(f"```output\nError: {error_text}\n```")

                    # Collect output for LLM
                    if result.success:
                        outputs.append(result.result or "")
                    else:
                        outputs.append(f"Error: {result.error}")

                # Add assistant message and tool results to conversation
                messages_to_send.append(ChatMessage(role="assistant", content=response.content))

                # Format tool output clearly - tell LLM to continue
                tool_output = chr(10).join(outputs) if outputs else "(no output)"
                tool_message = (
                    f"[Code executed. Output:]\n{tool_output}\n\n"
                    "[Now respond naturally to the user based on this result.]"
                )
                messages_to_send.append(ChatMessage(role="user", content=tool_message))

                print(f"[Agent] Tool output sent: {tool_output[:100]}...")

                final_response = response

            # Phase 1: Show raw output (don't strip code blocks)
            if final_response:
                display_content = final_response.content

                # If response was only code blocks and we have tool outputs, show something
                if not display_content and all_tool_calls:
                    last_result = all_tool_calls[-1]
                    if last_result["success"] and last_result["result"]:
                        display_content = last_result["result"]
                    elif not last_result["success"]:
                        display_content = f"Error: {last_result['error']}"
                    else:
                        display_content = "(Tool executed successfully)"
            else:
                display_content = "No response from LLM"

            # Add response to history and display
            if final_response:
                self._conversation_history.append(
                    ChatMessage(role="assistant", content=final_response.content)
                )

                # Trim history after adding response
                self._trim_history()

                if display_content:
                    assistant_turn.append_markdown(f"**Final:**\n\n{display_content}")
                else:
                    assistant_turn.append_markdown("**Final:**\n\n(No response text)")

                # Update status with iteration count
                iter_info = f" ({len(all_tool_calls)} tool calls)" if all_tool_calls else ""
                self._status_bar.set_info(f"Model: {final_response.model}{iter_info}")

        except HubError as e:
            self._chat_area.add_system_message(f"Error: {e}")
        except Exception as e:
            self._chat_area.add_system_message(f"Unexpected error: {e}")
        finally:
            self._input_area.set_sending(False)
            self._input_area.set_focus()

    async def _send_message_via_tensorzero(self, message: str):
        """Send message via TensorZero with Hub/local fallback and tool call support.

        Uses TensorZero gateway which handles fallback between Hub and local Ollama.
        Supports agent loop with TensorZero native tool calls.
        """
        MAX_ITERATIONS = 5

        try:
            assistant_turn = self._chat_area.add_assistant_turn("(Thinking...)")

            # Build messages for TensorZero
            tz_messages = []

            # Add conversation history
            for msg in self._conversation_history:
                # tensorzero/openai often reject 'system' messages in the middle of history
                if msg.role == "system":
                    continue
                tz_messages.append(ChatMessage(role=msg.role, content=msg.content))

            # Add current message
            tz_messages.append(ChatMessage(role="user", content=message))

            # Add to local history
            self._conversation_history.append(
                ChatMessage(role="user", content=message)
            )
            self._trim_history()

            # Get system prompt
            system_prompt = None
            if self._skill_service:
                system_prompt = self._skill_service.get_system_prompt()

            # Agent loop for tool calls
            all_tool_calls = []
            final_response = None
            tool_results = []  # Initialize for first iteration

            for iteration in range(MAX_ITERATIONS):
                print(f"[TZ Agent] Iteration {iteration + 1}/{MAX_ITERATIONS}")

                # Send to TensorZero
                if iteration == 0 or not tool_results:
                    response = await self._tensorzero_client.chat(
                        messages=tz_messages,
                        system_prompt=system_prompt,
                        temperature=self.settings.llm.temperature,
                    )
                else:
                    # Continue with tool results
                    response = await self._tensorzero_client.chat_with_tool_results(
                        messages=tz_messages,
                        tool_results=tool_results,
                        system_prompt=system_prompt,
                        temperature=self.settings.llm.temperature,
                    )

                # Track offline mode based on response
                self._offline_tracker.on_response(response)

                content_preview = response.content[:100] if response.content else ""
                tool_count = len(response.tool_calls)
                print(f"[TZ Agent] Response: {content_preview}... Tools: {tool_count}")

                # Check for tool calls
                if not response.tool_calls:
                    # No tool calls - agent is done
                    final_response = response
                    print("[TZ Agent] No tool calls, ending loop")
                    break

                # Display intermediate response if any
                if response.content and iteration == 0 and assistant_turn:
                    assistant_turn.set_markdown(f"**Step {iteration + 1}:**\n\n{response.content}")
                elif response.content:
                    step_md = f"\n\n**Step {iteration + 1}:**\n\n{response.content}"
                    assistant_turn.append_markdown(step_md)

                # Execute tool calls
                tool_results = []
                for tool_call in response.tool_calls:
                    tool_name = tool_call.name or "unknown_tool"
                    tool_args = tool_call.arguments or {}
                    if tool_name == "unknown_tool":
                        print("[TZ Agent] Skipping malformed tool call (missing tool name)")
                    else:
                        print(f"[TZ Agent] Executing tool: {tool_name}")

                    # Execute tool via skill service
                    if tool_name == "unknown_tool":
                        result = {
                            "error": (
                                "Malformed tool call from model (missing tool name). "
                                "Please call a valid tool."
                            ),
                        }
                    elif self._skill_service:
                        result = await self._skill_service.execute_tool_async(
                            tool_name,
                            tool_args,
                        )
                        # Provide guidance for unknown tools
                        if "Unknown tool" in result.get("error", ""):
                            result["error"] += (
                                " Use python_exec to call skills. Example: "
                                'python_exec({"code": "print(device.SkillName.method())"})'
                            )
                    else:
                        result = {"error": "Skill service not available"}

                    # Track tool call
                    tool_call_info = {
                        "iteration": iteration + 1,
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                        "result": result,
                    }
                    all_tool_calls.append(tool_call_info)

                    # Display tool call in UI (Integrated Notebook Style)
                    # For TZ native tools, show results similar to the local path
                    if "result" in result:
                        output_text = str(result["result"])
                        assistant_turn.append_markdown(f"```output\n{output_text}\n```")
                    else:
                        error_text = result.get("error", "Unknown error")
                        assistant_turn.append_markdown(f"```output\nError: {error_text}\n```")

                    # Build tool result for TensorZero
                    tool_results.append({
                        "id": tool_call.id,
                        "name": tool_name,
                        "result": result.get("result", result.get("error", "")),
                    })

                # Add assistant response to messages for next iteration
                tz_messages.append(ChatMessage(role="assistant", content=response.content))

                final_response = response

            # Update pending sync count
            if self._sync_manager:
                self._offline_tracker.pending_sync_count = self._sync_manager.get_pending_count()

            # Process final response
            display_content = final_response.content if final_response else "No response"

            # Store assistant response locally
            if self._session_db and self._current_session_id and final_response:
                msg = self._session_db.add_message(
                    self._current_session_id, "assistant", final_response.content
                )
                if self._sync_manager:
                    asyncio.ensure_future(
                        self._sync_manager.queue_add_message(
                            self._current_session_id, msg.id, "assistant", final_response.content
                        )
                    )

            # Add to conversation history
            if final_response:
                self._conversation_history.append(
                    ChatMessage(role="assistant", content=final_response.content)
                )
                self._trim_history()

            # Update UI with final response
            if display_content:
                if all_tool_calls:
                    assistant_turn.append_markdown(f"\n\n**Final:**\n\n{display_content}")
                else:
                    assistant_turn.set_markdown(display_content)

            # Update status with model/variant info
            if final_response:
                is_fb = final_response.is_fallback
                variant_info = f" (via {final_response.variant})" if is_fb else ""
                tool_info = f" ({len(all_tool_calls)} tools)" if all_tool_calls else ""
                self._status_bar.set_info(f"Model: {final_response.model}{variant_info}{tool_info}")

        except Exception as e:
            traceback.print_exc()
            self._chat_area.add_system_message(f"Error: {e}")
        finally:
            self._input_area.set_sending(False)
            self._input_area.set_focus()

    def _trim_history(self) -> None:
        """Trim conversation history to prevent unbounded memory growth.

        Keeps the most recent messages up to the configured max_history limit.
        """
        max_history = self.settings.conversation.max_history
        if len(self._conversation_history) > max_history:
            self._conversation_history = self._conversation_history[-max_history:]

    def _on_new_chat(self):
        """Start a new chat (clear history)."""
        self._conversation_history.clear()
        self._chat_area.clear_messages()
        self._current_session_id = None
        self._chat_sidebar.select_session(None)
        self._chat_area.add_system_message("New conversation started")
        self._input_area.set_focus()

        # Create new local session
        asyncio.ensure_future(self._create_local_session())

    async def _create_local_session(self):
        """Create a new local session and queue for Hub sync."""
        try:
            if self._session_db:
                session = self._session_db.create_session()
                self._current_session_id = session.id

                # Queue for Hub sync
                if self._sync_manager:
                    await self._sync_manager.queue_create_session(session.id)

                # Refresh session list
                await self._refresh_sessions()
        except Exception as e:
            print(f"Failed to create local session: {e}")

    async def _create_hub_session(self):
        """Create a new session on the Hub (legacy, used when no local storage)."""
        try:
            session = await self._hub_client.create_session()
            self._current_session_id = session["id"]
            await self._refresh_sessions()
        except Exception as e:
            print(f"Failed to create session: {e}")

    def _on_session_selected(self, session_id: str):
        """Load a session when selected from sidebar."""
        if session_id == getattr(self, "_current_session_id", None):
            return

        self._current_session_id = session_id
        self._conversation_history.clear()
        self._chat_area.clear_messages()

        # Load from local storage first
        if self._session_db:
            asyncio.ensure_future(self._load_local_session_messages(session_id))
        elif self._hub_client and self._connected:
            asyncio.ensure_future(self._load_session_messages(session_id))

    async def _load_local_session_messages(self, session_id: str):
        """Load messages for a session from local storage."""
        try:
            messages = self._session_db.get_messages(session_id)
            for msg in messages:
                chat_msg = ChatMessage(role=msg.role, content=msg.content)
                self._conversation_history.append(chat_msg)

                if msg.role == "user":
                    self._chat_area.add_user_message(msg.content)
                elif msg.role == "assistant":
                    self._chat_area.add_assistant_message(msg.content)
        except Exception as e:
            self._chat_area.add_system_message(f"Failed to load messages: {e}")

    async def _load_session_messages(self, session_id: str):
        """Load messages for a session from the Hub."""
        try:
            messages = await self._hub_client.get_session_messages(session_id)
            for msg in messages:
                chat_msg = ChatMessage(role=msg["role"], content=msg["content"])
                self._conversation_history.append(chat_msg)

                if msg["role"] == "user":
                    self._chat_area.add_user_message(msg["content"])
                elif msg["role"] == "assistant":
                    self._chat_area.add_assistant_message(msg["content"])
        except Exception as e:
            self._chat_area.add_system_message(f"Failed to load messages: {e}")

    def _on_session_deleted(self, session_id: str):
        """Delete a session."""
        if self._session_db:
            asyncio.ensure_future(self._delete_local_session(session_id))
        elif self._hub_client and self._connected:
            asyncio.ensure_future(self._delete_hub_session(session_id))

    async def _delete_local_session(self, session_id: str):
        """Delete a session from local storage and queue Hub sync."""
        try:
            if self._sync_manager:
                await self._sync_manager.queue_delete_session(session_id)
            else:
                self._session_db.delete_session(session_id)

            # If deleting current session, start new chat
            if session_id == getattr(self, "_current_session_id", None):
                self._on_new_chat()
            await self._refresh_sessions()
        except Exception as e:
            print(f"Failed to delete session: {e}")

    async def _delete_hub_session(self, session_id: str):
        """Delete a session on the Hub."""
        try:
            await self._hub_client.delete_session(session_id)
            # If deleting current session, start new chat
            if session_id == getattr(self, "_current_session_id", None):
                self._on_new_chat()
            await self._refresh_sessions()
        except Exception as e:
            print(f"Failed to delete session: {e}")

    async def _refresh_sessions(self):
        """Refresh the session list from local storage (with Hub merge if available)."""
        try:
            sessions_data = []

            # Get local sessions
            if self._session_db:
                local_sessions = self._session_db.list_sessions()
                for session in local_sessions:
                    sessions_data.append({
                        "id": session.id,
                        "hub_id": session.hub_id,
                        "title": session.title,
                        "message_count": self._session_db.get_session_message_count(session.id),
                        "last_activity": session.last_activity,
                        "sync_status": session.sync_status.value,
                    })

            # If no local storage but Hub connected, use Hub sessions
            elif self._hub_client and self._connected:
                sessions_data = await self._hub_client.list_sessions()

            self._chat_sidebar.set_sessions(sessions_data)
        except Exception as e:
            print(f"Failed to refresh sessions: {e}")

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

                # Use the correct endpoint: /api/v1/chat/completions (OpenAI-compatible)
                response = await client.post(
                    "/api/v1/chat/completions",
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
                    self._conversation_history.append(
                        ChatMessage(role="assistant", content=response_text)
                    )

                    return response_text
                else:
                    return f"Hub error: {response.status_code}"

        except Exception as e:
            return f"Error: {e}"

    @Slot(str)
    def _on_voice_state_changed(self, state: str):
        """Handle voice state changes."""
        self._voice_indicator.set_state(state)

        # Also update mic button state
        if state == "recording":
            self._input_area.set_mic_state(MicState.RECORDING)
        elif state == "processing":
            self._input_area.set_mic_state(MicState.PROCESSING)
        elif state in ("idle", "listening"):
            self._input_area.set_mic_state(MicState.IDLE)

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

    def open_settings_dialog(self) -> None:
        """Open the settings dialog."""
        self._on_settings()

    def _apply_settings_changes(self, changes: dict):
        """Apply settings changes from dialog."""
        project_root = Path(__file__).resolve().parents[3]

        # Persist changes first (best effort). Non-secrets go to config/config.yaml.
        # Secrets (tokens/API keys) go to .env and are applied immediately.
        yaml_updates = {}
        env_updates = {}

        if "device" in changes:
            yaml_updates["device.name"] = changes["device"].get("name", self.settings.device.name)

        if "hub" in changes:
            yaml_updates["hub.url"] = changes["hub"].get("url", self.settings.hub.url)

        if "skills" in changes:
            yaml_updates["skills.path"] = changes["skills"].get("path", self.settings.skills.path)

        if "ui" in changes:
            yaml_updates["ui.theme"] = changes["ui"].get("theme", self.settings.ui.theme)
            yaml_updates["ui.start_minimized"] = changes["ui"].get(
                "start_minimized", self.settings.ui.start_minimized
            )
            yaml_updates["ui.show_waveform"] = changes["ui"].get(
                "show_waveform", self.settings.ui.show_waveform
            )

        if "env" in changes:
            env_updates.update(changes["env"] or {})

        # Ensure Hub token is stored as HUB_DEVICE_TOKEN (TensorZero + Hub auth)
        # and also as HUB_TOKEN for backward compatibility with config.yaml's ${HUB_TOKEN} pattern
        if "hub" in changes and "token" in changes["hub"]:
            token = changes["hub"].get("token")
            env_updates["HUB_DEVICE_TOKEN"] = token
            env_updates["HUB_TOKEN"] = token

            # Eagerly apply in-memory so reconnect works even if file persistence fails.
            if token:
                os.environ["HUB_DEVICE_TOKEN"] = token
                os.environ["HUB_TOKEN"] = token

        try:
            result = persist_settings_and_env(
                config_path=project_root / "config" / "config.yaml",
                env_path=project_root / ".env",
                yaml_updates=yaml_updates,
                env_updates=env_updates,
            )
            if result.wrote_config or result.wrote_env:
                self._chat_area.add_system_message("Settings saved")
        except Exception as e:
            self._chat_area.add_system_message(f"Failed to save settings: {e}")

        # Update in-memory settings
        if "device" in changes:
            self.settings.device.name = changes["device"].get("name", self.settings.device.name)

        if "hub" in changes:
            old_url = self.settings.hub.url
            old_token = self.settings.hub.token

            self.settings.hub.url = changes["hub"].get("url", self.settings.hub.url)
            # Hub token is sourced from env; prefer HUB_DEVICE_TOKEN
            self.settings.hub.token = (
                os.environ.get("HUB_DEVICE_TOKEN")
                or os.environ.get("HUB_TOKEN")
                or changes["hub"].get("token", self.settings.hub.token)
            )

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

            self.settings.ui.show_waveform = changes["ui"].get(
                "show_waveform", self.settings.ui.show_waveform
            )

        if "skills" in changes:
            old_skills_path = self.settings.skills.path
            self.settings.skills.path = changes["skills"].get("path", self.settings.skills.path)
            if self.settings.skills.path != old_skills_path and self._skill_service:
                # Reload skills to pick up new directory and any env-dependent skill init
                self._init_skills()

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

    def _on_mic_button_clicked(self):
        """Handle mic button click - toggle voice recording.

        Click 1: Start recording (like wake word was detected)
        Click 2: Stop recording and process
        """
        # Check if already recording
        if self._voice_controller and self._voice_controller.is_push_to_talk_active():
            # Stop recording
            self._voice_controller.push_to_talk_stop()
            self._input_area.set_mic_state(MicState.PROCESSING)
            return

        # Start recording - ensure voice mode is enabled first
        if not self._voice_controller or not self._voice_controller.is_running():
            # Enable voice mode
            self._voice_toggle_action.setChecked(True)
            self._enable_voice()

        # Start recording
        if self._voice_controller:
            self._voice_controller.push_to_talk_start()
            self._input_area.set_mic_state(MicState.RECORDING)

    def _toggle_audio_feedback(self, enabled: bool):
        """Toggle audio feedback sounds."""
        self.settings.voice.audio_feedback_enabled = enabled

        if self._voice_controller:
            self._voice_controller.set_audio_feedback_enabled(enabled)

        status = "enabled" if enabled else "disabled"
        self._chat_area.add_system_message(f"Audio feedback {status}")

    def closeEvent(self, event):
        """Handle window close."""
        self.closing.emit()

        # Cleanup voice
        if self._voice_controller:
            self._voice_controller.stop()

        # Cleanup Hub client
        if self._hub_client:
            asyncio.ensure_future(self._hub_client.close())

        # Cleanup TensorZero client
        if self._tensorzero_client:
            asyncio.ensure_future(self._tensorzero_client.close())

        # Cleanup local storage
        if self._session_db:
            self._session_db.close()

        # Stop background sync
        if self._sync_manager:
            self._sync_manager.stop_background_sync()

        event.accept()

    def show_and_activate(self):
        """Show window and bring to front."""
        self.show()
        self.raise_()
        self.activateWindow()
        self._input_area.set_focus()

