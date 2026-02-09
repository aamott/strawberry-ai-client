"""Application entry point for GUI V2."""

import asyncio
import logging
import sys
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

if TYPE_CHECKING:
    from ...shared.settings import SettingsManager
    from ...spoke_core import SpokeCore
    from ...voice import VoiceCore

from ...spoke_core.events import SkillsLoaded
from .components.toast import ToastLevel
from .main_window import MainWindow
from .models.message import Message, MessageRole, TextSegment
from .models.state import ConnectionStatus, MessageSource, VoiceStatus

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
        settings_manager: Optional["SettingsManager"] = None,
    ):
        self._window = window
        self._core = spoke_core
        self._voice = voice_core
        self._settings_manager = settings_manager
        self._loop = loop
        self._subscription = None
        self._current_session_id: Optional[str] = None
        self._current_assistant_card = None
        self._pending_tool_calls: dict = {}
        # Maps UI session UUIDs → SpokeCore session IDs so we can
        # restore conversations when switching sessions.
        self._ui_to_core_session: dict[str, str] = {}
        # True when _on_new_chat already added a sidebar entry for the
        # current (not-yet-created) SpokeCore session.
        self._sidebar_entry_pending = False
        # Track how the last message was produced so we know whether to
        # speak the assistant response via TTS.
        self._last_message_source: MessageSource = MessageSource.TYPED

        self._connect_window_signals()
        if self._voice:
            self._connect_voice_signals()

    def _connect_window_signals(self) -> None:
        """Connect window signals to handlers."""
        self._window.message_submitted.connect(self._on_message_submitted)
        self._window.session_changed.connect(self._on_session_changed)
        self._window.skill_toggled.connect(self._on_skill_toggled)
        self._window.closing.connect(self._on_closing)
        # Note: read-aloud is handled by MainWindow._on_read_aloud_requested
        # via VoiceService — no duplicate connection needed here.

    def _connect_voice_signals(self) -> None:
        """Connect VoiceCore events to handlers.

        MainWindow already wires record/voice-mode buttons to its VoiceService.
        Here we only subscribe to VoiceCore events that IntegratedApp cares about
        (transcriptions → send as chat messages, errors → status bar).
        """
        # Set VoiceCore on the window's VoiceService so it can control it
        self._window.voice_service.set_voice_core(self._voice)

        # When a transcription arrives, send it as a chat message
        self._window.voice_service.transcription_received.connect(
            self._on_voice_transcription
        )

    def _on_voice_transcription(self, text: str, is_final: bool) -> None:
        """Handle voice transcription → display in chat and send.

        Routes through MainWindow.submit_message so the user bubble appears
        in the chat view. The source is VOICE_MODE if wakeword listening is
        active, otherwise VOICE_RECORD (record button tap/hold).
        """
        if not (is_final and text):
            return

        # Determine source based on whether voice mode (wakeword) is active
        if self._window.voice_service.is_voice_mode_active:
            source = MessageSource.VOICE_MODE
        else:
            source = MessageSource.VOICE_RECORD

        # submit_message adds the user bubble, then emits message_submitted
        # which triggers _on_message_submitted
        self._window.submit_message(text, source)

    def _subscribe_to_core_events(self) -> None:
        """Subscribe to SpokeCore events. Must be called after core.start()."""
        self._subscription = self._core.subscribe(self._on_core_event)

    def _on_session_changed(self, session_id: str) -> None:
        """Handle session change (new chat or sidebar session switch).

        If the UI session has a corresponding SpokeCore session, restore
        the SpokeCore session ID and reload its messages.  Otherwise
        reset to a blank state (new chat).

        Args:
            session_id: The UI session UUID.
        """
        logger.debug("Session changed to %s — resetting conversation state", session_id)
        self._current_assistant_card = None
        self._pending_tool_calls.clear()

        core_id = self._ui_to_core_session.get(session_id)
        if core_id:
            # Restore the existing SpokeCore session
            self._current_session_id = core_id
            self._sidebar_entry_pending = True
            self._reload_session_messages(core_id)
        else:
            # Brand-new chat — no SpokeCore session yet
            self._current_session_id = None
            self._sidebar_entry_pending = True

    def _reload_session_messages(self, core_session_id: str) -> None:
        """Reload messages from a SpokeCore session into the chat view.

        Args:
            core_session_id: The SpokeCore session ID to reload.
        """
        session = self._core.get_session(core_session_id)
        if not session:
            logger.warning("SpokeCore session %s not found", core_session_id)
            return

        for msg in session.messages:
            role = MessageRole.USER if msg.role == "user" else MessageRole.ASSISTANT
            gui_msg = Message(
                id=str(id(msg)),
                role=role,
                timestamp=datetime.now(),
                segments=[TextSegment(content=msg.content)],
            )
            self._window.chat_view.chat_area.add_message(gui_msg)

    def _on_message_submitted(self, content: str, source: str = "typed") -> None:
        """Handle message submission from GUI.

        Args:
            content: Message text.
            source: MessageSource value string (typed, voice_record, voice_mode).
        """
        # Remember the source so we can decide whether to speak the response
        try:
            self._last_message_source = MessageSource(source)
        except ValueError:
            self._last_message_source = MessageSource.TYPED
        asyncio.ensure_future(self._send_message(content))

    async def _send_message(self, content: str) -> None:
        """Send message to SpokeCore and handle response."""
        # Ensure we have a UI session ID (used by the sidebar). When the app
        # starts, no UI session exists until the first send; generate one here.
        ui_session_id = self._window._state.current_session_id
        if not ui_session_id:
            ui_session_id = str(uuid4())
            self._window._state.current_session_id = ui_session_id
            # Add sidebar entry for the initial chat if none was added yet.
            title = datetime.now().strftime("%b %d, %I:%M %p")
            self._window.sidebar.add_session(ui_session_id, title)
            self._window.sidebar.highlight_session(ui_session_id)
            # Mark that the sidebar already has this UI session entry.
            self._sidebar_entry_pending = True

        if not self._current_session_id:
            session = self._core.new_session()
            self._current_session_id = session.id
            # Record the UI→Core mapping so we can restore on switch
            self._ui_to_core_session[ui_session_id] = session.id
            # Only add a sidebar entry if _on_new_chat didn't already.
            if not self._sidebar_entry_pending:
                title = datetime.now().strftime("%b %d, %I:%M %p")
                self._window.sidebar.add_session(ui_session_id, title)
                self._window.sidebar.highlight_session(ui_session_id)
            self._sidebar_entry_pending = False

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
            SkillsLoaded,
            SkillStatusChanged,
            StreamingDelta,
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

        elif isinstance(event, StreamingDelta):
            # Append streaming text chunk to the current assistant card
            if self._current_assistant_card:
                self._current_assistant_card.append_text(event.delta)

        elif isinstance(event, MessageAdded):
            if event.role == "assistant" and self._current_assistant_card:
                # Append the final text if streaming deltas haven't already
                # provided it.  We check for existing *text* segments rather
                # than any segment, because tool-call segments don't count.
                has_text = any(
                    isinstance(s, TextSegment)
                    for s in self._current_assistant_card.message.segments
                )
                if not has_text and event.content:
                    self._current_assistant_card.append_text(event.content)
                self._window.finish_assistant_message(
                    self._current_assistant_card.message.id
                )

                # Speak the response via TTS when appropriate.
                # Voice Mode always speaks; the "read_responses_aloud"
                # setting speaks for *all* sources (typed, record, voice).
                # We only call speak() once to avoid double-playback.
                self._maybe_speak_response(event.content)

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
                self._window.toast.show(
                    "Hub connected", ToastLevel.SUCCESS, duration_ms=2500,
                )
            else:
                self._window.set_connection_status(
                    ConnectionStatus.DISCONNECTED,
                    event.error,
                )
                self._window.toast.show(
                    event.error or "Hub disconnected",
                    ToastLevel.WARNING,
                    duration_ms=5000,
                )

        elif isinstance(event, SkillsLoaded):
            # Queue toasts to ensure the window is ready before showing them
            toast_payloads = []

            # Load failures (errors)
            for failure in event.failures:
                toast_payloads.append(
                    (
                        f"Skill failed to load: {failure['source']}\n{failure['error']}",
                        ToastLevel.ERROR,
                    )
                )

            # Loaded but unhealthy (warnings)
            for skill in event.skills:
                if not skill.get("healthy", True):
                    msg = skill.get("health_message", "Unknown issue")
                    toast_payloads.append(
                        (
                            f"{skill['name']}: {msg}",
                            ToastLevel.WARNING,
                        )
                    )

            if toast_payloads:
                logger.info("Emitting skill health/load toasts: %s", toast_payloads)

                def _show_startup_toasts(payloads=toast_payloads):
                    for text, level in payloads:
                        self._window.toast.show(text, level, duration_ms=6000)

                # Show immediately; hub toasts already prove UI is ready.
                _show_startup_toasts()

            # Feed skill data to the skills panel
            self._window.set_skills_data(event.skills, event.failures)

        elif isinstance(event, SkillStatusChanged):
            # Refresh skills panel with updated data
            summaries = self._core.get_skill_summaries()
            failures = self._core.get_skill_load_failures()
            self._window.set_skills_data(summaries, failures)

        elif isinstance(event, ModeChanged):
            self._window.set_offline_mode(not event.online)
            if event.online:
                self._window.toast.show(
                    "Online mode restored", ToastLevel.SUCCESS, duration_ms=2500,
                )
            else:
                self._window.toast.show(
                    "Switched to offline mode",
                    ToastLevel.WARNING,
                    duration_ms=4000,
                )

    def _read_responses_aloud_enabled(self) -> bool:
        """Check the voice_core general.read_responses_aloud setting."""
        sm = self._settings_manager or self._window._settings_manager
        if sm and sm.is_registered("voice_core"):
            return bool(sm.get("voice_core", "general.read_responses_aloud", False))
        return False

    def _maybe_speak_response(self, content: str) -> None:
        """Speak an assistant response via TTS if appropriate.

        Called once per assistant message. Speaks if:
        - The user used Voice Mode (always), OR
        - The "read responses aloud" setting is enabled (any source).

        Only calls speak() once to avoid double-playback.
        """
        if not self._voice or not content:
            return

        should_speak = (
            self._last_message_source == MessageSource.VOICE_MODE
            or self._read_responses_aloud_enabled()
        )
        if should_speak:
            self._voice.speak(content)

    def _on_skill_toggled(self, name: str, enabled: bool) -> None:
        """Handle skill enable/disable from the skills panel.

        Args:
            name: Skill class name.
            enabled: New enabled state.
        """
        asyncio.ensure_future(self._core.set_skill_enabled(name, enabled))

    def _on_closing(self) -> None:
        """Handle window closing."""
        # Schedule shutdown - the loop will process it before fully closing
        asyncio.ensure_future(self._shutdown())

    async def _shutdown(self) -> None:
        """Shutdown SpokeCore and VoiceCore."""
        logger.info("Shutting down...")
        if self._subscription:
            self._subscription.cancel()
        # VoiceService manages the VoiceCore listener; just stop VoiceCore
        if self._voice and self._voice.is_running():
            await self._voice.stop()
        await self._core.stop()
        # Allow pending httpx/httpcore cleanup tasks to complete
        await asyncio.sleep(0.1)
        logger.info("Shutdown complete")

    def _should_autostart_voice(self) -> bool:
        """Check the voice_core general.autostart setting."""
        sm = self._window._settings_manager
        if sm and sm.is_registered("voice_core"):
            return bool(sm.get("voice_core", "general.autostart", False))
        return False

    async def start(self) -> None:
        """Start SpokeCore, VoiceCore, and connect to Hub."""
        await self._core.start()

        # Subscribe to events after core is started (event bus has loop set)
        self._subscribe_to_core_events()

        # We may have missed the initial SkillsLoaded emitted during
        # core.start(); manually dispatch once so the GUI sees health/toasts.
        summaries = self._core.get_skill_summaries()
        failures = self._core.get_skill_load_failures()
        self._on_core_event(SkillsLoaded(skills=summaries, failures=failures))

        # Set up VoiceCore (response handler) regardless of autostart
        if self._voice:
            self._voice.set_response_handler(self._handle_voice_response)

            # Only auto-start if the setting says so; otherwise the voice
            # buttons will lazy-start VoiceCore on first click.
            if self._should_autostart_voice():
                logger.info("Autostart enabled — starting VoiceCore")
                self._window.set_voice_status(VoiceStatus.STARTING)
                voice_started = await self._voice.start()
                if voice_started:
                    logger.info("VoiceCore started (autostart)")
                    self._window.set_voice_status(VoiceStatus.IDLE)
                else:
                    logger.warning("VoiceCore failed to start")
                    self._window.set_voice_status(VoiceStatus.ERROR)
            else:
                logger.info("VoiceCore available but autostart disabled — will start on demand")

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


def _ensure_voice_core(
    voice_core: Optional["VoiceCore"],
    settings_manager: "SettingsManager",
) -> Optional["VoiceCore"]:
    """Create a VoiceCore instance if one was not provided.

    VoiceCore is created but NOT started — it will be started lazily
    on first button click or via the autostart setting.

    Args:
        voice_core: Existing VoiceCore or None.
        settings_manager: SettingsManager for config and backend discovery.

    Returns:
        A VoiceCore instance, or None if voice deps are unavailable.
    """
    if voice_core is not None:
        return voice_core

    try:
        from ...voice import VoiceConfig, VoiceCore

        # VoiceCore reads actual values from SettingsManager during init;
        # we just supply a default VoiceConfig as the base.
        config = VoiceConfig()
        voice_core = VoiceCore(
            config=config,
            settings_manager=settings_manager,
        )
        logger.info("Created VoiceCore (not yet started)")
        return voice_core
    except ImportError as e:
        logger.warning("Voice dependencies not available: %s", e)
        return None
    except Exception:
        logger.exception("Failed to create VoiceCore")
        return None


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

    # Create VoiceCore if not provided (lazy — not started yet)
    voice_core = _ensure_voice_core(voice_core, settings_manager)

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
    integrated = IntegratedApp(
        window, spoke_core, loop, voice_core, settings_manager
    )

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
