"""Application entry point for GUI V2."""

import asyncio
import logging
import sys
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

if TYPE_CHECKING:
    from ...shared.settings import SettingsManager
    from ...spoke_core import SpokeCore
    from ...voice import VoiceCore

from .main_window import MainWindow
from .models.state import ConnectionStatus, VoiceStatus

logger = logging.getLogger(__name__)


def _ensure_settings_manager(
    settings_manager: Optional["SettingsManager"] = None,
) -> "SettingsManager":
    """Create a SettingsManager if one was not provided.

    Args:
        settings_manager: Existing manager or None.

    Returns:
        A ready-to-use SettingsManager.
    """
    if settings_manager is not None:
        return settings_manager

    from ...shared.settings import SettingsManager
    from ...utils.paths import get_project_root

    config_dir = get_project_root() / "config"
    return SettingsManager(config_dir=config_dir, env_filename="../.env")


def run_app(
    settings_manager: Optional["SettingsManager"] = None,
    voice_core: Optional["VoiceCore"] = None,
) -> int:
    """Run the GUI V2 application.

    Args:
        settings_manager: Optional settings manager instance
        voice_core: Optional voice core instance

    Returns:
        Application exit code
    """
    # Ensure we always have a SettingsManager
    settings_manager = _ensure_settings_manager(settings_manager)

    # Create Qt application
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    # Set application metadata
    app.setApplicationName("Strawberry AI")
    app.setApplicationVersion("2.0.0")
    app.setOrganizationName("Strawberry")

    # Create and show main window
    window = MainWindow(
        settings_manager=settings_manager,
        voice_core=voice_core,
    )
    window.show()

    logger.info("GUI V2 started")

    # Run event loop
    return app.exec()


def run_app_async(
    settings_manager: Optional["SettingsManager"] = None,
    voice_core: Optional["VoiceCore"] = None,
) -> int:
    """Run the GUI V2 application with asyncio integration.

    Uses qasync to integrate Qt event loop with asyncio.

    Args:
        settings_manager: Optional settings manager instance
        voice_core: Optional voice core instance

    Returns:
        Application exit code
    """
    try:
        import qasync
    except ImportError:
        logger.warning("qasync not installed, falling back to sync mode")
        return run_app(settings_manager, voice_core)

    # Ensure we always have a SettingsManager
    settings_manager = _ensure_settings_manager(settings_manager)

    # Create Qt application
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    # Set application metadata
    app.setApplicationName("Strawberry AI")
    app.setApplicationVersion("2.0.0")
    app.setOrganizationName("Strawberry")

    # Create async event loop
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    # Create and show main window
    window = MainWindow(
        settings_manager=settings_manager,
        voice_core=voice_core,
    )
    window.show()

    logger.info("GUI V2 started (async mode)")

    # Run event loop
    with loop:
        return loop.run_forever()


class IntegratedApp:
    """Integrated application that connects GUI V2 with SpokeCore and VoiceCore.

    Handles:
    - Initializing SpokeCore and connecting to Hub
    - Bridging SpokeCore events to GUI updates
    - Running the agent loop when messages are sent
    - Voice input via push-to-talk
    - TTS output for assistant responses
    """

    def __init__(
        self,
        window: MainWindow,
        spoke_core: "SpokeCore",
        loop: asyncio.AbstractEventLoop,
        voice_core: Optional["VoiceCore"] = None,
    ):
        self._window = window
        self._core = spoke_core
        self._voice = voice_core
        self._loop = loop
        self._subscription = None
        self._current_session_id: Optional[str] = None
        self._current_assistant_card = None
        self._pending_tool_calls: dict = {}

        self._connect_window_signals()
        if self._voice:
            self._connect_voice_signals()

    def _connect_window_signals(self) -> None:
        """Connect window signals to handlers."""
        self._window.message_submitted.connect(self._on_message_submitted)
        self._window.closing.connect(self._on_closing)

    def _connect_voice_signals(self) -> None:
        """Connect VoiceCore events to handlers."""
        self._voice.add_listener(self._on_voice_event)

        # Connect voice button in chat view to PTT
        self._window.chat_view.voice_pressed.connect(self._on_voice_pressed)
        self._window.chat_view.voice_released.connect(self._on_voice_released)

    def _on_voice_pressed(self) -> None:
        """Handle voice button press (start PTT)."""
        if self._voice and self._voice.is_running():
            self._voice.push_to_talk_start()
            self._window.set_voice_status(VoiceStatus.LISTENING)

    def _on_voice_released(self) -> None:
        """Handle voice button release (stop PTT)."""
        if self._voice and self._voice.is_push_to_talk_active():
            self._voice.push_to_talk_stop()
            self._window.set_voice_status(VoiceStatus.PROCESSING)

    def _on_voice_event(self, event) -> None:
        """Handle VoiceCore events."""
        from ...voice.events import (
            VoiceError,
            VoiceSpeaking,
            VoiceStateChanged,
            VoiceTranscription,
        )
        from ...voice.state import VoiceState

        if isinstance(event, VoiceStateChanged):
            # Update voice status indicator
            if event.new_state == VoiceState.IDLE:
                self._window.set_voice_status(VoiceStatus.IDLE)
            elif event.new_state == VoiceState.LISTENING:
                self._window.set_voice_status(VoiceStatus.LISTENING)
            elif event.new_state == VoiceState.PROCESSING:
                self._window.set_voice_status(VoiceStatus.PROCESSING)
            elif event.new_state == VoiceState.SPEAKING:
                self._window.set_voice_status(VoiceStatus.SPEAKING)

        elif isinstance(event, VoiceTranscription):
            if event.is_final and event.text:
                # Send transcribed text as a message
                self._on_message_submitted(event.text)

        elif isinstance(event, VoiceSpeaking):
            logger.debug(f"TTS speaking: {event.text[:50]}...")

        elif isinstance(event, VoiceError):
            logger.error(f"Voice error: {event.error}")
            self._window.status_bar.flash_message(f"Voice error: {event.error}")
            self._window.set_voice_status(VoiceStatus.ERROR)

    def _subscribe_to_core_events(self) -> None:
        """Subscribe to SpokeCore events. Must be called after core.start()."""
        self._subscription = self._core.subscribe(self._on_core_event)

    def _on_message_submitted(self, content: str) -> None:
        """Handle message submission from GUI."""
        asyncio.ensure_future(self._send_message(content), loop=self._loop)

    async def _send_message(self, content: str) -> None:
        """Send message to SpokeCore and handle response."""
        if not self._current_session_id:
            session = self._core.new_session()
            self._current_session_id = session.id
            self._window.sidebar.add_session(session.id, "New Chat")
            self._window.sidebar.highlight_session(session.id)

        # Create assistant message card for streaming
        self._current_assistant_card = self._window.add_assistant_message()

        try:
            await self._core.send_message(self._current_session_id, content)
        except Exception as e:
            logger.exception("Error sending message")
            self._window.chat_view.set_typing(False)
            self._window.chat_view.set_input_enabled(True)
            self._window.status_bar.flash_message(f"Error: {e}")

    def _on_core_event(self, event) -> None:
        """Handle SpokeCore events and update GUI."""
        from ...spoke_core.events import (
            ConnectionChanged,
            CoreError,
            CoreReady,
            MessageAdded,
            ModeChanged,
            ToolCallResult,
            ToolCallStarted,
        )

        if isinstance(event, CoreReady):
            logger.info("SpokeCore ready")

        elif isinstance(event, CoreError):
            logger.error(f"Core error: {event.error}")
            self._window.status_bar.flash_message(f"Error: {event.error}")
            self._window.chat_view.set_typing(False)
            self._window.chat_view.set_input_enabled(True)

        elif isinstance(event, MessageAdded):
            if event.role == "assistant" and self._current_assistant_card:
                self._current_assistant_card.append_text(event.content)
                self._window.finish_assistant_message(
                    self._current_assistant_card.message.id
                )
                self._current_assistant_card = None

        elif isinstance(event, ToolCallStarted):
            if self._current_assistant_card:
                idx = self._current_assistant_card.add_tool_call(
                    tool_name=event.tool_name,
                    arguments=event.arguments,
                )
                self._pending_tool_calls[event.tool_name] = idx

        elif isinstance(event, ToolCallResult):
            if self._current_assistant_card:
                result = event.result if event.success else event.error
                self._current_assistant_card.update_tool_call(
                    tool_name=event.tool_name,
                    result=result if event.success else None,
                    error=result if not event.success else None,
                )

        elif isinstance(event, ConnectionChanged):
            if event.connected:
                self._window.set_connection_status(ConnectionStatus.CONNECTED)
            else:
                self._window.set_connection_status(
                    ConnectionStatus.DISCONNECTED,
                    event.error,
                )

        elif isinstance(event, ModeChanged):
            self._window.set_offline_mode(not event.online)

    def _on_closing(self) -> None:
        """Handle window closing."""
        # Schedule shutdown - the loop will process it before fully closing
        asyncio.ensure_future(self._shutdown(), loop=self._loop)

    async def _shutdown(self) -> None:
        """Shutdown SpokeCore and VoiceCore."""
        logger.info("Shutting down...")
        if self._subscription:
            self._subscription.cancel()
        if self._voice:
            self._voice.remove_listener(self._on_voice_event)
            await self._voice.stop()
        await self._core.stop()
        # Allow pending httpx/httpcore cleanup tasks to complete
        await asyncio.sleep(0.1)
        logger.info("Shutdown complete")

    async def start(self) -> None:
        """Start SpokeCore, VoiceCore, and connect to Hub."""
        await self._core.start()

        # Subscribe to events after core is started (event bus has loop set)
        self._subscribe_to_core_events()

        # Start VoiceCore if available
        if self._voice:
            # Set response handler to speak assistant responses
            self._voice.set_response_handler(self._handle_voice_response)
            voice_started = await self._voice.start()
            if voice_started:
                logger.info("VoiceCore started")
                self._window.set_voice_status(VoiceStatus.IDLE)
            else:
                logger.warning("VoiceCore failed to start")

        # Try to connect to Hub
        device_name = self._core._get_setting("device.name", "Strawberry Spoke")
        self._window.set_device_name(device_name)

        connected = await self._core.connect_hub()
        if not connected:
            self._window.set_offline_mode(True)
            self._window.set_connection_status(ConnectionStatus.DISCONNECTED)

    def _handle_voice_response(self, text: str) -> str:
        """Handle voice transcription by sending to SpokeCore.

        This is called by VoiceCore when speech is transcribed.
        We return empty string since we handle the response via events.
        """
        # The transcription is handled via VoiceTranscription event
        return ""


def run_app_integrated(
    settings_manager: Optional["SettingsManager"] = None,
    voice_core: Optional["VoiceCore"] = None,
) -> int:
    """Run the fully integrated GUI V2 application with SpokeCore.

    This is the recommended entry point for production use.

    Args:
        settings_manager: Optional settings manager instance
        voice_core: Optional voice core instance

    Returns:
        Application exit code
    """
    try:
        import qasync
    except ImportError:
        logger.error("qasync is required for integrated mode")
        return 1

    from ...spoke_core import SpokeCore

    # Ensure we always have a SettingsManager
    settings_manager = _ensure_settings_manager(settings_manager)

    # Create Qt application
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    app.setApplicationName("Strawberry AI")
    app.setApplicationVersion("2.0.0")
    app.setOrganizationName("Strawberry")

    # Create async event loop
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    # Create SpokeCore
    spoke_core = SpokeCore(settings_manager=settings_manager)

    # Create main window
    window = MainWindow(
        settings_manager=settings_manager,
        voice_core=voice_core,
    )

    # Create integrated app
    integrated = IntegratedApp(window, spoke_core, loop, voice_core)

    # Start SpokeCore after window is shown
    window.show()

    async def startup():
        await integrated.start()

    QTimer.singleShot(100, lambda: asyncio.ensure_future(startup()))

    logger.info("GUI V2 started (integrated mode)")

    with loop:
        return loop.run_forever()


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Run the integrated app (SettingsManager created automatically)
    # Note: httpcore may print "no running event loop" errors during shutdown.
    # These are cosmetic and don't affect functionality - they occur because
    # qasync closes the event loop before httpcore can clean up connections.
    sys.exit(run_app_integrated())
