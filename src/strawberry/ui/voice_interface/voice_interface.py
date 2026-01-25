"""VoiceInterface - Voice-only interaction example.

This module provides a standalone voice interface that wires VoiceCore
events to SpokeCore for a voice-only assistant experience.

Usage:
    strawberry-voice           # Run as command
    python -m strawberry.ui.voice_interface  # Run as module
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import TYPE_CHECKING, Optional

from ...spoke_core import SpokeCore
from ...voice import (
    VoiceConfig,
    VoiceCore,
    VoiceError,
    VoiceListening,
    VoiceSpeaking,
    VoiceState,
    VoiceStateChanged,
    VoiceTranscription,
    VoiceWakeWordDetected,
)

if TYPE_CHECKING:
    from ...shared.settings import SettingsManager

logger = logging.getLogger(__name__)


class VoiceInterface:
    """Voice-only interface - wires VoiceCore events to SpokeCore.

    This class orchestrates a voice-only assistant experience:
    1. VoiceCore handles wake word detection, STT, and TTS
    2. When transcription completes, it's sent to SpokeCore
    3. When SpokeCore responds, the response is spoken via VoiceCore

    Usage:
        interface = VoiceInterface()
        await interface.start()
        # Voice interaction happens automatically
        await interface.stop()
    """

    def __init__(
        self,
        spoke_core: Optional[SpokeCore] = None,
        voice_core: Optional[VoiceCore] = None,
        settings_manager: Optional["SettingsManager"] = None,
    ):
        """Initialize VoiceInterface.

        Args:
            spoke_core: Optional SpokeCore instance (creates one if not provided)
            voice_core: Optional VoiceCore instance (creates one if not provided)
            settings_manager: Optional SettingsManager for shared settings.
                If provided, will be passed to SpokeCore and VoiceCore.
        """
        self._spoke_core = spoke_core
        self._voice_core = voice_core
        self._settings_manager = settings_manager
        self._session_id: Optional[str] = None
        self._running = False
        self._owns_spoke_core = spoke_core is None
        self._owns_voice_core = voice_core is None
        self._printed_offline_notice = False

    def _build_voice_config(self) -> VoiceConfig:
        """Build VoiceConfig from SettingsManager.

        Returns:
            Configured VoiceConfig instance.
        """
        if self._settings_manager:
            mgr = self._settings_manager
            wake_phrase = mgr.get("voice_core", "wakeword.phrase", "strawberry")
            wake_words = [w.strip() for w in str(wake_phrase).split(",") if w.strip()]
            return VoiceConfig(
                wake_words=wake_words or ["strawberry"],
                sensitivity=float(mgr.get("voice_core", "wakeword.sensitivity", 0.5)),
                sample_rate=int(mgr.get("voice_core", "audio.sample_rate", 16000)),
                stt_backend=mgr.get("voice_core", "stt.order", "leopard"),
                tts_backend=mgr.get("voice_core", "tts.order", "pocket"),
                vad_backend=mgr.get("voice_core", "vad.order", "silero"),
                wake_backend=mgr.get("voice_core", "wakeword.order", "porcupine"),
            )

        # Return defaults if no SettingsManager
        return VoiceConfig()

    async def start(self) -> bool:
        """Start the voice interface.

        Returns:
            True if started successfully.
        """
        try:
            # Create SpokeCore if not provided
            if self._spoke_core is None:
                self._spoke_core = SpokeCore(settings_manager=self._settings_manager)
                await self._spoke_core.start()

            # Create session
            session = self._spoke_core.new_session()
            self._session_id = session.id

            # Create VoiceCore if not provided
            if self._voice_core is None:
                # Get voice config from SettingsManager or fall back to legacy settings
                voice_config = self._build_voice_config()
                self._voice_core = VoiceCore(
                    config=voice_config,
                    settings_manager=self._settings_manager,
                )

            # Wire events
            self._wire_events()

            # Start voice core
            if not await self._voice_core.start():
                logger.error("Failed to start VoiceCore")
                return False

            self._running = True
            logger.info("VoiceInterface started")
            return True

        except Exception as e:
            logger.exception(f"Failed to start VoiceInterface: {e}")
            return False

    async def stop(self) -> None:
        """Stop the voice interface."""
        self._running = False

        if self._voice_core and self._owns_voice_core:
            await self._voice_core.stop()

        if self._spoke_core and self._owns_spoke_core:
            await self._spoke_core.stop()

        logger.info("VoiceInterface stopped")

    def _wire_events(self) -> None:
        """Wire VoiceCore events to handlers."""
        if self._voice_core:
            self._voice_core.add_listener(self._on_voice_event)

    def _on_voice_event(self, event) -> None:
        """Handle voice events.

        Args:
            event: Voice event from VoiceCore
        """
        if isinstance(event, VoiceWakeWordDetected):
            print(f"🎤 Wake word detected: '{event.keyword}'")

        elif isinstance(event, VoiceListening):
            print("🎤 Listening...")

        elif isinstance(event, VoiceTranscription):
            if event.is_final and event.text:
                print(f"🗣️ You: {event.text}")
                # Send to SpokeCore
                return self._process_transcription(event.text)

        elif isinstance(event, VoiceSpeaking):
            print(f"🔊 Speaking: {event.text[:80]}...")

        elif isinstance(event, VoiceStateChanged):
            logger.debug(f"State: {event.old_state.name} → {event.new_state.name}")

            if event.new_state == VoiceState.ERROR:
                print("❌ Voice entered a failed state; exiting")
                return self._shutdown_and_exit()

        elif isinstance(event, VoiceError):
            print(f"❌ Voice error: {event.error}")

        return None

    async def _process_transcription(self, text: str) -> None:
        """Send transcription to SpokeCore and speak the response.

        Args:
            text: Transcribed speech text
        """
        if not self._spoke_core or not self._session_id:
            return

        try:
            if (
                self._spoke_core
                and not self._spoke_core.is_online()
                and not self._printed_offline_notice
            ):
                print("(Hub not connected; using local mode)")
                self._printed_offline_notice = True

            # Send to SpokeCore and get response
            response = await self._spoke_core.send_message(self._session_id, text)

            if response and self._voice_core:
                print(f"🤖 Assistant: {response[:100]}...")
                self._voice_core.speak(response)

        except Exception as e:
            logger.error(f"Error processing transcription: {e}")
            print(f"❌ Error: {e}")

    async def run_forever(self) -> None:
        """Run until interrupted."""
        if not await self.start():
            print("Failed to start voice interface")
            return

        print("\n" + "=" * 50)
        print("🍓 Strawberry Voice Interface")
        print("=" * 50)
        wake_words = ", ".join(
            self._voice_core._config.wake_words if self._voice_core else ["strawberry"]
        )
        print(f"Say '{wake_words}' to activate")
        print("Press Ctrl+C to exit")
        print("=" * 50 + "\n")

        # Wait for interrupt
        stop_event = asyncio.Event()

        def signal_handler():
            stop_event.set()

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, signal_handler)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass

        try:
            await stop_event.wait()
        except KeyboardInterrupt:
            pass
        finally:
            print("\n\nShutting down...")
            await self.stop()
            print("Goodbye!")

    async def _shutdown_and_exit(self) -> None:
        """Stop the interface and exit the process.

        This is used when VoiceCore enters an unrecoverable error state.
        """
        await self.stop()
        raise SystemExit(1)


def main() -> None:
    """Entry point for strawberry-voice command."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Suppress noisy loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # Silence TensorZero Rust logs
    os.environ.setdefault("RUST_LOG", "off")

    # Create SettingsManager for shared settings
    from ...shared.settings import SettingsManager
    from ...utils.paths import get_project_root

    config_dir = get_project_root() / "config"
    settings_manager = SettingsManager(
        config_dir=config_dir,
        env_filename="../.env",  # Use root .env for secrets
    )

    interface = VoiceInterface(settings_manager=settings_manager)
    try:
        asyncio.run(interface.run_forever())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
