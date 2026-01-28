"""Voice processing engine - manages STT/TTS/VAD/WakeWord pipelines.

This module provides a clean, importable API for voice processing that can
be used by any UI:
- CLI with /voice toggle
- VoiceInterface standalone example
- Future UIs

The audio stream remains open throughout the voice session to prevent
frame loss between components.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Sequence

import numpy as np

from .audio.backends.sounddevice_backend import SoundDeviceBackend
from .audio.playback import AudioPlayer
from .audio.stream import AudioStream
from .state import VoiceState, VoiceStateError, can_transition
from .stt import STTEngine, discover_stt_modules
from .tts import TTSEngine, discover_tts_modules
from .vad import VADBackend, VADProcessor, discover_vad_modules
from .wakeword import WakeWordDetector, discover_wake_modules

if TYPE_CHECKING:
    from strawberry.shared.settings import SettingsManager

logger = logging.getLogger(__name__)


# =============================================================================
# Events
# =============================================================================


@dataclass
class VoiceEvent:
    """Base class for voice events."""

    session_id: str = ""


@dataclass
class VoiceStateChanged(VoiceEvent):
    """Voice state has changed."""

    old_state: VoiceState = VoiceState.STOPPED
    new_state: VoiceState = VoiceState.STOPPED


@dataclass
class VoiceWakeWordDetected(VoiceEvent):
    """Wake word was detected."""

    keyword: str = ""
    keyword_index: int = 0


@dataclass
class VoiceListening(VoiceEvent):
    """Voice is now listening for speech."""

    pass


@dataclass
class VoiceNoSpeechDetected(VoiceEvent):
    """Recording ended without detecting any speech.

    This is emitted when we enter LISTENING (after wake word / PTT) but VAD
    determines that no speech occurred before recording ended.
    """

    duration_s: float = 0.0


@dataclass
class VoiceTranscription(VoiceEvent):
    """Speech was transcribed."""

    text: str = ""
    is_final: bool = True
    confidence: float = 1.0


@dataclass
class VoiceResponse(VoiceEvent):
    """Response text (for TTS or display)."""

    text: str = ""


@dataclass
class VoiceSpeaking(VoiceEvent):
    """TTS is playing response."""

    text: str = ""


@dataclass
class VoiceError(VoiceEvent):
    """An error occurred in voice pipeline."""

    error: str = ""
    exception: Optional[Exception] = None


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class VoiceConfig:
    """Configuration for VoiceCore.

    Attributes:
        wake_words: List of wake word phrases to detect.
        sensitivity: Wake word detection sensitivity (0.0-1.0).
        sample_rate: Audio sample rate in Hz.
        audio_feedback_enabled: Whether to play audio feedback sounds.
        stt_backend: Speech-to-text backend module name.
        tts_backend: Text-to-speech backend module name.
        vad_backend: Voice activity detection backend module name.
        wake_backend: Wake word detection backend module name.
    """

    wake_words: List[str] = field(default_factory=lambda: ["hey barista"])
    sensitivity: float = 0.5
    sample_rate: int = 16000
    audio_feedback_enabled: bool = True

    # Backend selection (module names). Each value supports ordered fallback:
    # - A single backend name (e.g. "leopard")
    # - A comma-separated string (e.g. "leopard,google,mock")
    # - A list of backend names (e.g. ["leopard", "google", "mock"])
    stt_backend: str | Sequence[str] = "leopard"
    tts_backend: str | Sequence[str] = "pocket"
    vad_backend: str | Sequence[str] = "silero"
    wake_backend: str | Sequence[str] = "porcupine"


# =============================================================================
# VoiceCore
# =============================================================================


class VoiceCore:
    """Voice processing engine.

    Manages the voice interaction pipeline including wake word detection,
    speech recognition, and text-to-speech. Uses asyncio for event handling.

    The audio stream is kept open throughout the voice session to prevent
    frame loss between wake word detection and STT.

    Usage:
        core = VoiceCore(config)
        core.add_listener(my_event_handler)
        await core.start()
        # ... voice interaction happens ...
        await core.stop()

    Public API:
        - Lifecycle: start(), stop()
        - Listening: start_listening(), stop_listening(), trigger_wakeword()
        - Speaking: speak(text), stop_speaking()
        - State: get_state()
        - Events: add_listener(cb), remove_listener(cb)
    """

    def __init__(
        self,
        config: VoiceConfig,
        response_handler: Optional[Callable[[str], str]] = None,
        settings_manager: Optional["SettingsManager"] = None,
    ):
        """Initialize VoiceCore.

        Args:
            config: Voice configuration.
            response_handler: Callback(transcription) -> response_text.
            settings_manager: Optional SettingsManager for shared settings.
                If provided, VoiceCore will register its namespace and backend
                namespaces with the manager.
        """
        self._config = config
        self._response_handler = response_handler
        self._settings_manager = settings_manager

        # State
        self._state = VoiceState.STOPPED
        self._state_lock = threading.Lock()
        self._session_id = ""
        self._session_counter = 0

        # Components (lazy initialized)
        self._wake_detector: Optional[WakeWordDetector] = None
        self._vad: Optional[VADBackend] = None
        self._vad_processor: Optional[VADProcessor] = None
        self._stt: Optional[STTEngine] = None
        self._tts: Optional[TTSEngine] = None
        self._audio_player: Optional[AudioPlayer] = None

        # Backend fallback bookkeeping
        self._stt_backend_names: list[str] = []
        self._tts_backend_names: list[str] = []
        self._active_stt_backend: Optional[str] = None

        # Cached module discovery (to avoid re-scanning on every speech)
        self._stt_modules: dict[str, type[STTEngine]] = {}
        self._tts_modules: dict[str, type[TTSEngine]] = {}
        self._vad_modules: dict[str, type[VADBackend]] = {}
        self._wake_modules: dict[str, type[WakeWordDetector]] = {}

        # Audio stream (kept open to avoid frame loss)
        self._audio_backend: Optional[SoundDeviceBackend] = None
        self._audio_stream: Optional[AudioStream] = None
        self._recording_buffer: List[np.ndarray] = []
        self._recording_start_time: float = 0
        self._max_recording_duration: float = 30.0
        self._last_frame_time: float = 0
        self._frame_timeout: float = 5.0  # Watchdog: max seconds without frames

        # Event listeners
        self._listeners: List[Callable[[VoiceEvent], Any]] = []

        # Push-to-talk state
        self._ptt_active = False

        # Asyncio loop used for scheduling coroutine listeners from worker threads
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

        # Watchdog thread
        self._watchdog_thread: Optional[threading.Thread] = None
        self._watchdog_stop = threading.Event()

        # Speaking pipeline queue
        self._speak_queue: queue.Queue[str] = queue.Queue()
        self._speak_thread: Optional[threading.Thread] = None
        self._speak_stop = threading.Event()

        # Backend re-initialization tracking
        self._reinit_pending: set[str] = set()  # Track which component types need re-init
        self._active_tts_backend: Optional[str] = None
        self._active_vad_backend: Optional[str] = None
        self._active_wake_backend: Optional[str] = None

        # Register with SettingsManager if provided
        if self._settings_manager:
            self._register_with_settings_manager()

    def _register_with_settings_manager(self) -> None:
        """Register VoiceCore's namespace and backend namespaces with SettingsManager."""
        if not self._settings_manager:
            return

        from .settings_schema import VOICE_CORE_SCHEMA

        # Register voice_core namespace if not already registered
        if not self._settings_manager.is_registered("voice_core"):
            self._settings_manager.register(
                namespace="voice_core",
                display_name="Voice",
                schema=VOICE_CORE_SCHEMA,
                order=20,
            )

            # Sync config to manager
            self._sync_config_to_manager()

        # Register backend namespaces
        self._register_backend_namespaces()

        # Listen for settings changes
        self._settings_manager.on_change(self._on_settings_changed)

    def _sync_config_to_manager(self) -> None:
        """Sync VoiceConfig with SettingsManager.

        - Reads existing values from SettingsManager (loaded from settings.yaml)
        - Updates VoiceConfig with those values
        - Only writes defaults for keys that don't exist yet
        """
        if not self._settings_manager:
            return

        cfg = self._config

        # Convert backend fields to comma-separated strings if needed
        def to_order_string(val: str | Sequence[str]) -> str:
            if isinstance(val, str):
                return val
            return ",".join(val)

        # Keys to sync with their default values
        keys_and_defaults = [
            ("stt.order", to_order_string(cfg.stt_backend)),
            ("tts.order", to_order_string(cfg.tts_backend)),
            ("vad.order", to_order_string(cfg.vad_backend)),
            ("wakeword.order", to_order_string(cfg.wake_backend)),
            ("wakeword.phrase", ",".join(cfg.wake_words) if cfg.wake_words else "hey barista"),
            ("wakeword.sensitivity", cfg.sensitivity),
            ("audio.sample_rate", str(cfg.sample_rate)),
            ("audio.feedback_enabled", cfg.audio_feedback_enabled),
        ]

        for key, default_value in keys_and_defaults:
            existing = self._settings_manager.get("voice_core", key)
            if existing is not None:
                # Update VoiceConfig from settings (settings.yaml takes priority)
                self._update_config_from_settings(key, existing)
            else:
                # Write default to settings manager
                self._settings_manager.set(
                    "voice_core", key, default_value, skip_validation=True
                )

    def _register_backend_namespaces(self) -> None:
        """Register settings namespaces for all discovered backends."""
        if not self._settings_manager:
            return

        # Use cached modules if available, otherwise discover and cache
        if not self._stt_modules:
            self._stt_modules = discover_stt_modules()
        if not self._tts_modules:
            self._tts_modules = discover_tts_modules()
        if not self._vad_modules:
            self._vad_modules = discover_vad_modules()
        if not self._wake_modules:
            self._wake_modules = discover_wake_modules()

        # Register STT backends
        for name, cls in self._stt_modules.items():
            namespace = f"voice.stt.{name}"
            if not self._settings_manager.is_registered(namespace):
                schema = cls.get_settings_schema()
                if schema:
                    self._settings_manager.register(
                        namespace=namespace,
                        display_name=f"STT: {cls.name}",
                        schema=schema,
                        order=100,
                    )

        # Register TTS backends
        for name, cls in self._tts_modules.items():
            namespace = f"voice.tts.{name}"
            if not self._settings_manager.is_registered(namespace):
                schema = cls.get_settings_schema()
                if schema:
                    self._settings_manager.register(
                        namespace=namespace,
                        display_name=f"TTS: {cls.name}",
                        schema=schema,
                        order=100,
                    )

        # Register VAD backends
        for name, cls in self._vad_modules.items():
            namespace = f"voice.vad.{name}"
            if not self._settings_manager.is_registered(namespace):
                schema = cls.get_settings_schema()
                if schema:
                    self._settings_manager.register(
                        namespace=namespace,
                        display_name=f"VAD: {cls.name}",
                        schema=schema,
                        order=100,
                    )

        # Register wake word backends
        for name, cls in self._wake_modules.items():
            namespace = f"voice.wakeword.{name}"
            if not self._settings_manager.is_registered(namespace):
                schema = cls.get_settings_schema()
                if schema:
                    self._settings_manager.register(
                        namespace=namespace,
                        display_name=f"Wake: {cls.name}",
                        schema=schema,
                        order=100,
                    )

    def _on_settings_changed(self, namespace: str, key: str, value: Any) -> None:
        """Handle settings changes from the SettingsManager.

        Updates config and schedules backend re-initialization if needed.
        """
        if not namespace.startswith("voice"):
            return

        # Update config if voice_core settings changed
        if namespace == "voice_core":
            self._update_config_from_settings(key, value)

            # Schedule re-init if backend order changed while running
            if self._state != VoiceState.STOPPED:
                if key == "stt.order":
                    self._reinit_pending.add("stt")
                    logger.info("STT backend order changed - re-init pending")
                    self._stt_backend_names = self._parse_backend_names(self._config.stt_backend)
                elif key == "tts.order":
                    self._reinit_pending.add("tts")
                    logger.info("TTS backend order changed - re-init pending")
                    self._tts_backend_names = self._parse_backend_names(self._config.tts_backend)
                elif key == "vad.order":
                    self._reinit_pending.add("vad")
                    logger.info("VAD backend order changed - re-init pending")
                elif key == "wakeword.order":
                    self._reinit_pending.add("wakeword")
                    logger.info("WakeWord backend order changed - re-init pending")

                # If we're already idle, apply changes immediately.
                if self._state == VoiceState.IDLE and self.has_pending_reinit():
                    self._trigger_pending_reinit()

        # If a backend's specific settings changed, mark for re-init
        elif namespace.startswith("voice.stt.") and self._state != VoiceState.STOPPED:
            backend_name = namespace.split(".")[2]
            if backend_name == self._active_stt_backend:
                self._reinit_pending.add("stt")
                logger.info(f"STT backend '{backend_name}' settings changed - re-init pending")
        elif namespace.startswith("voice.tts.") and self._state != VoiceState.STOPPED:
            backend_name = namespace.split(".")[2]
            if backend_name == self._active_tts_backend:
                self._reinit_pending.add("tts")
                logger.info(f"TTS backend '{backend_name}' settings changed - re-init pending")
        elif namespace.startswith("voice.vad.") and self._state != VoiceState.STOPPED:
            backend_name = namespace.split(".")[2]
            if backend_name == self._active_vad_backend:
                self._reinit_pending.add("vad")
                logger.info(f"VAD backend '{backend_name}' settings changed - re-init pending")
        elif namespace.startswith("voice.wakeword.") and self._state != VoiceState.STOPPED:
            backend_name = namespace.split(".")[3] if len(namespace.split(".")) > 3 else ""
            if backend_name == self._active_wake_backend:
                self._reinit_pending.add("wakeword")
                logger.info(f"WakeWord backend '{backend_name}' settings changed - re-init pending")

    def _update_config_from_settings(self, key: str, value: Any) -> None:
        """Update VoiceConfig from a settings change."""
        cfg = self._config

        if key == "wakeword.phrase":
            cfg.wake_words = [w.strip() for w in str(value).split(",") if w.strip()]
        elif key == "wakeword.sensitivity":
            cfg.sensitivity = float(value) if value else 0.5
        elif key == "audio.sample_rate":
            cfg.sample_rate = int(value) if value else 16000
        elif key == "audio.feedback_enabled":
            cfg.audio_feedback_enabled = bool(value)
        elif key == "stt.order":
            cfg.stt_backend = str(value) if value else "leopard"
        elif key == "tts.order":
            cfg.tts_backend = str(value) if value else "pocket"
        elif key == "vad.order":
            cfg.vad_backend = str(value) if value else "silero"
        elif key == "wakeword.order":
            cfg.wake_backend = str(value) if value else "porcupine"

    def _get_backend_settings(self, backend_type: str, backend_name: str) -> dict[str, Any]:
        """Get settings for a specific backend from SettingsManager.

        Args:
            backend_type: Type of backend ("stt", "tts", "vad", "wakeword").
            backend_name: Name of the specific backend (e.g., "leopard").

        Returns:
            Dict of setting key -> value for the backend.
        """
        if not self._settings_manager:
            return {}

        namespace = f"voice.{backend_type}.{backend_name}"
        return self._settings_manager.get_all(namespace) or {}

    @property
    def settings_manager(self) -> Optional["SettingsManager"]:
        """Get the SettingsManager if one was provided."""
        return self._settings_manager

    def refresh_module_discovery(self) -> None:
        """Re-discover voice backend modules.

        Call this after settings change (e.g., API key added) to pick up
        backends that may now be available. Does not reinitialize active
        backends - that requires stop() and start().
        """
        logger.info("Refreshing voice module discovery")
        self._stt_modules = discover_stt_modules()
        self._tts_modules = discover_tts_modules()
        self._vad_modules = discover_vad_modules()
        self._wake_modules = discover_wake_modules()

    async def reinitialize_pending_backends(self) -> bool:
        """Reinitialize backends that have had settings changes.

        Call this when ready to apply pending settings changes. This is
        typically done when entering IDLE state or via user trigger.

        Returns:
            True if all pending reinits succeeded, False otherwise.
        """
        if not self._reinit_pending:
            return True

        if self._state == VoiceState.STOPPED:
            logger.warning("Cannot reinitialize backends - VoiceCore is stopped")
            return False

        logger.info(f"Reinitializing backends: {self._reinit_pending}")
        success = True
        pending = self._reinit_pending.copy()
        self._reinit_pending.clear()

        # STT reinitialization
        if "stt" in pending:
            try:
                if self._stt:
                    self._stt.cleanup()
                    self._stt = None

                stt_backend_names = self._parse_backend_names(self._config.stt_backend)
                for name in stt_backend_names:
                    try:
                        self._init_stt_backend_or_raise(
                            stt_modules=self._stt_modules, name=name
                        )
                        logger.info(f"STT backend reinitialized: {name}")
                        break
                    except Exception as e:
                        logger.warning(f"STT backend '{name}' reinit failed: {e}")

                if not self._stt:
                    logger.error("All STT backends failed to reinitialize")
                    success = False
            except Exception as e:
                logger.error(f"STT reinitialization error: {e}")
                success = False

        # TTS reinitialization
        if "tts" in pending:
            try:
                if self._tts:
                    self._tts.cleanup()
                    self._tts = None

                tts_backend_names = self._parse_backend_names(self._config.tts_backend)
                for name in tts_backend_names:
                    tts_cls = self._tts_modules.get(name)
                    if not tts_cls:
                        continue
                    try:
                        backend_settings = self._get_backend_settings("tts", name)
                        self._tts = tts_cls(**backend_settings)
                        self._audio_player = AudioPlayer(sample_rate=self._tts.sample_rate)
                        self._active_tts_backend = name
                        logger.info(f"TTS backend reinitialized: {name}")
                        break
                    except Exception as e:
                        logger.warning(f"TTS backend '{name}' reinit failed: {e}")

                if not self._tts:
                    logger.error("All TTS backends failed to reinitialize")
                    success = False
            except Exception as e:
                logger.error(f"TTS reinitialization error: {e}")
                success = False

        # VAD and wakeword require full restart due to audio stream dependencies
        if "vad" in pending or "wakeword" in pending:
            logger.info(
                "VAD/WakeWord changes require full voice restart. "
                "Call stop() and start() to apply."
            )
            # Add back to pending for user awareness
            if "vad" in pending:
                self._reinit_pending.add("vad")
            if "wakeword" in pending:
                self._reinit_pending.add("wakeword")

        return success

    def has_pending_reinit(self) -> bool:
        """Check if any backends have pending reinitialization.

        Returns:
            True if reinitialize_pending_backends() should be called.
        """
        return bool(self._reinit_pending)

    # -------------------------------------------------------------------------
    # Public API: State
    # -------------------------------------------------------------------------

    def get_state(self) -> VoiceState:
        """Get current voice state.

        Returns:
            Current VoiceState enum value.
        """
        return self._state

    @property
    def state(self) -> VoiceState:
        """Current voice state (property alias for get_state)."""
        return self._state

    @property
    def session_id(self) -> str:
        """Current voice session ID."""
        return self._session_id

    def is_running(self) -> bool:
        """Check if voice core is running (not stopped)."""
        return self._state != VoiceState.STOPPED

    def is_push_to_talk_active(self) -> bool:
        """Check if push-to-talk recording is active."""
        return self._ptt_active

    # -------------------------------------------------------------------------
    # Public API: Events
    # -------------------------------------------------------------------------

    def add_listener(self, listener: Callable[[VoiceEvent], Any]) -> None:
        """Add event listener.

        Args:
            listener: Callback function(event) for voice events
        """
        self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[VoiceEvent], Any]) -> None:
        """Remove event listener."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    # -------------------------------------------------------------------------
    # Public API: Lifecycle
    # -------------------------------------------------------------------------

    async def start(self) -> bool:
        """Start VoiceCore and begin listening for wake word.

        Returns:
            True if started successfully.
        """
        if self._state != VoiceState.STOPPED:
            logger.warning("VoiceCore already running")
            return False

        try:
            self._event_loop = asyncio.get_running_loop()
            await self._init_components()

            self._session_counter += 1
            self._session_id = f"voice-{self._session_counter}"

            if self._audio_stream:
                self._audio_stream.subscribe(self._on_audio_frame)
                self._audio_stream.start()
                logger.info(f"Listening for wake words: {self._config.wake_words}")

            # Start speaking worker
            self._speak_stop.clear()
            self._speak_thread = threading.Thread(target=self._speak_loop, daemon=True)
            self._speak_thread.start()

            # Start watchdog thread to detect stuck states
            self._watchdog_stop.clear()
            self._watchdog_thread = threading.Thread(
                target=self._watchdog_loop, daemon=True
            )
            self._watchdog_thread.start()

            self._transition_to(VoiceState.IDLE)
            logger.info("VoiceCore started")
            return True

        except Exception as e:
            logger.error(f"Failed to start VoiceCore: {e}")
            self._emit(VoiceError(error=str(e), exception=e))
            return False

    async def stop(self) -> None:
        """Stop VoiceCore and cleanup resources."""
        if self._state == VoiceState.STOPPED:
            return

        # Stop watchdog first
        self._watchdog_stop.set()
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=1.0)
            self._watchdog_thread = None

        # Stop speaking worker
        self.stop_speaking()
        self._speak_stop.set()
        if self._speak_thread:
            self._speak_thread.join(timeout=1.0)
            self._speak_thread = None

        try:
            self._transition_to(VoiceState.STOPPED)
        except VoiceStateError:
            with self._state_lock:
                self._state = VoiceState.STOPPED

        await self._cleanup_components()
        self._event_loop = None
        logger.info("VoiceCore stopped")

    # -------------------------------------------------------------------------
    # Public API: Listening Pipeline Control
    # -------------------------------------------------------------------------

    def start_listening(self) -> None:
        """Start wake word detection.

        Call this to resume listening after stop_listening().
        """
        if self._state == VoiceState.STOPPED:
            logger.warning("Cannot start listening - VoiceCore not running")
            return

        if self._state != VoiceState.IDLE:
            logger.debug(f"Already in state {self._state.name}, ignoring start_listening")
            return

        # Already in IDLE = already listening for wake word
        logger.debug("Listening for wake word")

    def stop_listening(self) -> None:
        """Stop wake word detection (pause listening)."""
        # This would pause the audio stream if needed
        # For now, stop() handles full cleanup
        logger.debug("stop_listening called (no-op in current impl)")

    def trigger_wakeword(self) -> None:
        """Skip wake word and start recording immediately (PTT mode).

        Use this for push-to-talk functionality where user presses a button
        instead of saying the wake word.
        """
        if self._state != VoiceState.IDLE:
            logger.warning(f"Cannot trigger wakeword in state {self._state.name}")
            return

        logger.info("Wake word triggered manually (PTT)")
        self._emit(VoiceWakeWordDetected(keyword="<manual>", keyword_index=-1))
        self._start_recording()

    def push_to_talk_start(self) -> None:
        """Start push-to-talk recording (sync version of trigger_wakeword)."""
        self._ptt_active = True
        self.trigger_wakeword()

    def push_to_talk_stop(self) -> None:
        """Stop push-to-talk and process recording."""
        if not self._ptt_active or self._state != VoiceState.LISTENING:
            return

        self._ptt_active = False
        self._finish_recording()

    # -------------------------------------------------------------------------
    # Public API: Speaking Pipeline Control
    # -------------------------------------------------------------------------

    def speak(self, text: str) -> None:
        """Queue text for TTS playback.

        Args:
            text: Text to speak. Code blocks are automatically stripped.
        """
        if not text:
            return

        if self._state == VoiceState.STOPPED:
            logger.warning("Cannot speak - VoiceCore is stopped")
            return

        self._speak_queue.put(text)

    def stop_speaking(self) -> None:
        """Interrupt current TTS playback."""
        if self._state == VoiceState.SPEAKING and self._audio_player:
            self._audio_player.stop()

        # Drop any queued speech
        while True:
            try:
                self._speak_queue.get_nowait()
            except queue.Empty:
                break

        # Transition back to idle if we were speaking
        if self._state == VoiceState.SPEAKING:
            try:
                self._transition_to(VoiceState.IDLE)
            except VoiceStateError:
                pass

    def set_response_handler(self, handler: Callable[[str], str]) -> None:
        """Set callback for processing transcriptions.

        Args:
            handler: Function(transcription) -> response_text
        """
        self._response_handler = handler

    def set_audio_feedback_enabled(self, enabled: bool) -> None:
        """Enable or disable audio feedback sounds.

        Args:
            enabled: Whether to play feedback sounds.
        """
        self._config.audio_feedback_enabled = enabled

    # -------------------------------------------------------------------------
    # Internal: Event Emission
    # -------------------------------------------------------------------------

    def _emit(self, event: VoiceEvent) -> None:
        """Emit event to all listeners."""
        event.session_id = self._session_id
        for listener in self._listeners:
            try:
                result = listener(event)
                if asyncio.iscoroutine(result):
                    if self._event_loop is None or self._event_loop.is_closed():
                        logger.error(
                            "Voice event listener returned coroutine but VoiceCore has no running "
                            "event loop"
                        )
                        continue

                    try:
                        running_loop = asyncio.get_running_loop()
                    except RuntimeError:
                        running_loop = None

                    if running_loop is self._event_loop:
                        self._event_loop.create_task(result)
                    else:
                        asyncio.run_coroutine_threadsafe(result, self._event_loop)
            except Exception as e:
                logger.error(f"Error in voice event listener: {e}")

    def _transition_to(self, new_state: VoiceState) -> None:
        """Transition to a new state.

        Args:
            new_state: Target state

        Raises:
            VoiceStateError: If transition is not valid
        """
        with self._state_lock:
            if not can_transition(self._state, new_state):
                raise VoiceStateError(self._state, new_state)

            old_state = self._state
            self._state = new_state
            logger.debug(f"Voice state: {old_state.name} → {new_state.name}")

        self._emit(VoiceStateChanged(old_state=old_state, new_state=new_state))

        # Apply any pending backend reinitializations when we reach a safe state.
        if new_state == VoiceState.IDLE and self.has_pending_reinit():
            self._trigger_pending_reinit()

    def _trigger_pending_reinit(self) -> None:
        """Trigger reinitialization of pending backends.

        This schedules reinitialize_pending_backends() on the VoiceCore event loop
        so changes (like TTS fallback order) take effect without needing a restart.
        """
        if not self._event_loop or not self._event_loop.is_running():
            return

        async def _apply() -> None:
            try:
                await self.reinitialize_pending_backends()
            except Exception as e:
                logger.error(f"Failed to apply pending voice backend changes: {e}")

        try:
            # If we're already on the event loop thread, create a task.
            asyncio.get_running_loop()
            asyncio.create_task(_apply())
        except RuntimeError:
            # Called from a worker thread.
            future: concurrent.futures.Future[None] = asyncio.run_coroutine_threadsafe(
                _apply(),
                self._event_loop,
            )

            def _done(f: concurrent.futures.Future[None]) -> None:
                try:
                    f.result()
                except Exception as e:
                    logger.error(f"Pending voice backend changes task failed: {e}")

            future.add_done_callback(_done)

    # -------------------------------------------------------------------------
    # Internal: Component Management
    # -------------------------------------------------------------------------

    async def _init_components(self) -> None:
        """Initialize voice pipeline components.

        Wake word detection is optional - if it fails, we can still use
        STT/TTS in push-to-talk mode via trigger_wakeword().
        """
        # Use cached modules if available, otherwise discover and cache
        # (discovery may have already happened in _register_backend_namespaces)
        if not self._stt_modules:
            self._stt_modules = discover_stt_modules()
        if not self._tts_modules:
            self._tts_modules = discover_tts_modules()
        if not self._vad_modules:
            self._vad_modules = discover_vad_modules()
        if not self._wake_modules:
            self._wake_modules = discover_wake_modules()

        # Use cached modules
        stt_modules = self._stt_modules
        tts_modules = self._tts_modules
        vad_modules = self._vad_modules
        wake_modules = self._wake_modules

        stt_backend_names = self._parse_backend_names(self._config.stt_backend)
        tts_backend_names = self._parse_backend_names(self._config.tts_backend)
        vad_backend_names = self._parse_backend_names(self._config.vad_backend)
        wake_backend_names = self._parse_backend_names(self._config.wake_backend)

        self._stt_backend_names = stt_backend_names

        # Initialize wake word detector (optional - may fail gracefully)
        wake_init_errors: list[str] = []
        for name in wake_backend_names:
            wake_cls = wake_modules.get(name)
            if not wake_cls:
                wake_init_errors.append(f"Wake backend '{name}' not found")
                continue
            try:
                # Get backend-specific settings from SettingsManager
                backend_settings = self._get_backend_settings("wakeword", name)

                self._wake_detector = wake_cls(
                    keywords=self._config.wake_words,
                    sensitivity=self._config.sensitivity,
                    **backend_settings,
                )
                self._active_wake_backend = name
                logger.info(f"Wake backend selected: {name}")
                break
            except Exception as e:
                msg = f"Wake backend '{name}' init failed: {e}"
                logger.warning(msg)
                wake_init_errors.append(msg)

        # Warn but don't fail if wake word detection unavailable
        if not self._wake_detector:
            logger.warning(
                "Wake word detection unavailable. "
                f"Tried: {wake_backend_names}. Errors: {wake_init_errors}. "
                "STT will still work via mic button (trigger_wakeword)."
            )

        # Initialize audio backend
        # Use wake detector's sample rate if available, otherwise use config
        if self._wake_detector:
            wake_frame_len = self._wake_detector.frame_length
            wake_sample_rate = self._wake_detector.sample_rate
            frame_ms = max(1, int(wake_frame_len * 1000 / wake_sample_rate))
        else:
            # Fallback audio settings when wake word is disabled/failed
            wake_sample_rate = self._config.sample_rate
            frame_ms = 30  # 30ms frames is common for STT

        self._audio_backend = SoundDeviceBackend(
            sample_rate=wake_sample_rate,
            frame_length_ms=frame_ms,
        )
        self._audio_stream = AudioStream(self._audio_backend)
        logger.info(f"Audio stream: {wake_sample_rate}Hz, {frame_ms}ms frames")

        # Initialize VAD (must match audio stream rate)
        vad_init_errors: list[str] = []
        for name in vad_backend_names:
            vad_cls = vad_modules.get(name)
            if not vad_cls:
                vad_init_errors.append(f"VAD backend '{name}' not found")
                continue
            try:
                # Get backend-specific settings from SettingsManager
                backend_settings = self._get_backend_settings("vad", name)

                self._vad = vad_cls(sample_rate=wake_sample_rate, **backend_settings)
                self._active_vad_backend = name
                logger.info(f"VAD backend selected: {name}")

                if hasattr(self._vad, "preload"):
                    logger.info("Preloading VAD model...")
                    self._vad.preload()

                from .vad.processor import VADConfig

                self._vad_processor = VADProcessor(
                    self._vad,
                    VADConfig(),
                    frame_duration_ms=frame_ms,
                )
                break
            except Exception as e:
                msg = f"VAD backend '{name}' init failed: {e}"
                logger.error(msg)
                vad_init_errors.append(msg)

        if not self._vad:
            raise RuntimeError(
                "VAD initialization failed. "
                f"Tried: {vad_backend_names}. Errors: {vad_init_errors}"
            )

        # Initialize STT
        stt_init_errors: list[str] = []
        for name in stt_backend_names:
            try:
                self._init_stt_backend_or_raise(stt_modules=stt_modules, name=name)
                break
            except Exception as e:
                msg = f"STT backend '{name}' init failed: {e}"
                logger.error(msg)
                stt_init_errors.append(msg)

        if not self._stt:
            raise RuntimeError(
                "STT initialization failed. "
                f"Tried: {stt_backend_names}. Errors: {stt_init_errors}"
            )

        # Initialize TTS
        tts_init_errors: list[str] = []
        self._tts_backend_names = tts_backend_names  # Store for runtime fallback
        for name in tts_backend_names:
            tts_cls = tts_modules.get(name)
            if not tts_cls:
                tts_init_errors.append(f"TTS backend '{name}' not found")
                continue

            # Check health before attempting initialization
            if not tts_cls.is_healthy():
                msg = tts_cls.health_check_error() or f"TTS backend '{name}' is unhealthy"
                logger.warning(f"Skipping TTS backend '{name}': {msg}")
                tts_init_errors.append(msg)
                continue

            try:
                # Get backend-specific settings from SettingsManager
                backend_settings = self._get_backend_settings("tts", name)

                self._tts = tts_cls(**backend_settings)
                self._audio_player = AudioPlayer(sample_rate=self._tts.sample_rate)
                self._active_tts_backend = name
                logger.info(f"TTS backend selected: {name}")
                break
            except Exception as e:
                msg = f"TTS backend '{name}' init failed: {e}"
                logger.error(msg)
                tts_init_errors.append(msg)

        if not self._tts or not self._audio_player:
            raise RuntimeError(
                "TTS initialization failed. "
                f"Tried: {tts_backend_names}. Errors: {tts_init_errors}"
            )

    def _init_stt_backend_or_raise(
        self,
        *,
        stt_modules: dict[str, type[STTEngine]],
        name: str,
    ) -> None:
        """Initialize a specific STT backend.

        Args:
            stt_modules: Discovered STT backend mapping.
            name: Backend module name.

        Raises:
            RuntimeError: If backend is not found or fails to initialize.
        """
        stt_cls = stt_modules.get(name)
        if not stt_cls:
            raise RuntimeError(f"STT backend '{name}' not found")

        # Get backend-specific settings from SettingsManager
        backend_settings = self._get_backend_settings("stt", name)

        self._stt = stt_cls(**backend_settings)
        self._active_stt_backend = name
        logger.info(f"STT backend selected: {name}")

    def _fail_voice_core(self, error: Exception) -> None:
        """Put VoiceCore into failed state and stop processing.

        This is used when all STT fallbacks fail.
        """
        logger.error(f"VoiceCore entering failed state: {error}")
        self._emit(VoiceError(error=str(error), exception=error))
        try:
            self._transition_to(VoiceState.ERROR)
        except VoiceStateError:
            with self._state_lock:
                self._state = VoiceState.ERROR

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            loop.create_task(self.stop())
        elif self._event_loop is not None and not self._event_loop.is_closed():
            asyncio.run_coroutine_threadsafe(self.stop(), self._event_loop)

    def _parse_backend_names(self, value: str | Sequence[str]) -> list[str]:
        """Normalize backend config values into an ordered list.

        Args:
            value: Backend selection as str, comma-separated str, or list.

        Returns:
            Ordered list of backend names to try.
        """
        if isinstance(value, str):
            names = [part.strip() for part in value.split(",")]
            return [name for name in names if name]

        names = [str(item).strip() for item in value]
        return [name for name in names if name]

    async def _cleanup_components(self) -> None:
        """Cleanup voice pipeline components."""
        if self._audio_stream:
            self._audio_stream.unsubscribe(self._on_audio_frame)
            self._audio_stream.stop()
            self._audio_stream = None

        if self._audio_backend:
            self._audio_backend = None

        if self._wake_detector:
            self._wake_detector.cleanup()
            self._wake_detector = None

        if self._vad:
            self._vad.cleanup()
            self._vad = None

        if self._stt:
            self._stt.cleanup()
            self._stt = None

        if self._tts:
            self._tts.cleanup()
            self._tts = None

    # -------------------------------------------------------------------------
    # Internal: Audio Processing
    # -------------------------------------------------------------------------

    def _on_audio_frame(self, frame) -> None:
        """Handle incoming audio frame based on current state."""
        if self._state == VoiceState.IDLE:
            self._handle_idle(frame)
        elif self._state == VoiceState.LISTENING:
            self._handle_listening(frame)

    def _handle_idle(self, frame) -> None:
        """Process frame while in IDLE state - check for wake word."""
        if not self._wake_detector:
            return

        try:
            keyword_index = self._wake_detector.process(frame)

            if keyword_index >= 0:
                keyword = self._wake_detector.keywords[keyword_index]
                logger.info(f"Wake word detected: {keyword}")

                self._emit(
                    VoiceWakeWordDetected(
                        keyword=keyword,
                        keyword_index=keyword_index,
                    )
                )
                self._start_recording()

        except Exception as e:
            logger.error(f"Error processing audio frame: {e}")

    def _start_recording(self) -> None:
        """Transition to listening and start recording audio."""
        self._recording_buffer.clear()
        self._recording_start_time = time.time()
        self._last_frame_time = 0
        if self._vad_processor:
            self._vad_processor.reset()
        self._transition_to(VoiceState.LISTENING)
        self._emit(VoiceListening())
        logger.info("Started recording")

    def _handle_listening(self, frame) -> None:
        """Process frame while recording - buffer audio and check VAD."""
        self._last_frame_time = time.time()  # Update for watchdog
        self._recording_buffer.append(frame)

        elapsed = time.time() - self._recording_start_time
        if elapsed > self._max_recording_duration:
            logger.warning(f"Recording timed out after {elapsed:.1f}s")
            self._finish_recording()
            return

        if self._vad_processor:
            speech_ended = self._vad_processor.process(frame)
            if speech_ended:
                logger.info(
                    f"VAD speech end after {self._vad_processor.session_duration:.2f}s"
                )
                self._finish_recording()
        elif elapsed > 3.0:
            logger.info("Recording timeout (no VAD)")
            self._finish_recording()

    def _finish_recording(self) -> None:
        """Process recorded audio through STT and response handler."""
        # If VAD never saw speech, don't waste STT cycles. Report the condition
        # and return to idle so UIs can reflect "no speech detected".
        if self._vad_processor and not self._vad_processor.speech_detected:
            duration_s = max(0.0, time.time() - self._recording_start_time)
            logger.info(
                "Recording ended with no speech detected (duration=%.2fs)", duration_s
            )
            self._recording_buffer.clear()
            self._emit(VoiceNoSpeechDetected(duration_s=duration_s))
            self._transition_to(VoiceState.IDLE)
            return

        self._transition_to(VoiceState.PROCESSING)

        if self._recording_buffer:
            audio = np.concatenate(self._recording_buffer)
        else:
            audio = np.array([], dtype=np.int16)
        self._recording_buffer.clear()

        logger.info(f"Recording finished: {len(audio)} samples")

        threading.Thread(
            target=self._process_audio_sync,
            args=(audio,),
            daemon=True,
        ).start()

    def _process_audio_sync(self, audio: np.ndarray) -> None:
        """Process audio through STT and get response (sync, runs in thread)."""
        try:
            if not self._stt:
                logger.warning("No STT engine available")
                self._transition_to(VoiceState.IDLE)
                return

            # Use cached modules (discovered once at init, not on every speech)
            stt_modules = self._stt_modules
            last_error: Optional[Exception] = None
            tried: list[str] = []
            backend_names = (
                self._stt_backend_names
                or ([] if self._active_stt_backend is None else [self._active_stt_backend])
            )
            for name in backend_names:
                if name in tried:
                    continue
                tried.append(name)

                if self._active_stt_backend != name or self._stt is None:
                    try:
                        self._init_stt_backend_or_raise(
                            stt_modules=stt_modules,
                            name=name,
                        )
                    except Exception as e:
                        last_error = e
                        self._emit(VoiceError(error=str(e), exception=e))
                        continue

                try:
                    result = self._stt.transcribe(audio)
                    break
                except Exception as e:
                    last_error = e
                    logger.error(f"STT backend '{name}' failed: {e}")
                    self._emit(VoiceError(error=str(e), exception=e))
                    self._stt = None
                    continue
            else:
                self._fail_voice_core(last_error or RuntimeError("All STT backends failed"))
                return

            text = result.text.strip() if result.text else ""

            if not text:
                logger.info("Empty transcription, returning to idle")
                self._transition_to(VoiceState.IDLE)
                return

            logger.info(f"Transcription: {text}")
            self._emit(VoiceTranscription(text=text, is_final=True))

            if self._response_handler:
                response = self._response_handler(text)
                logger.info(f"Response: {response[:50]}...")
                self._emit(VoiceResponse(text=response))
                self.speak(response)
            else:
                self._transition_to(VoiceState.IDLE)

        except Exception as e:
            logger.error(f"Error processing audio: {e}")
            self._emit(VoiceError(error=str(e), exception=e))
            self._transition_to(VoiceState.IDLE)

    def _speak_response(self, text: str) -> None:
        """Speak response text using TTS.

        If the current TTS backend fails, attempts to fall back to the next
        available backend in the configured fallback order.
        """
        if not self._tts or not self._audio_player:
            logger.warning("No TTS engine available")
            if self._state != VoiceState.IDLE:
                try:
                    self._transition_to(VoiceState.IDLE)
                except VoiceStateError:
                    pass
            return

        # Strip code blocks
        speakable_text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        speakable_text = re.sub(r"`[^`]+`", "", speakable_text)
        speakable_text = re.sub(r"\s+", " ", speakable_text).strip()

        if not speakable_text:
            logger.info("No speakable text after filtering")
            if self._state != VoiceState.IDLE:
                try:
                    self._transition_to(VoiceState.IDLE)
                except VoiceStateError:
                    pass
            return

        try:
            self._transition_to(VoiceState.SPEAKING)
            self._emit(VoiceSpeaking(text=speakable_text))

            self._synthesize_with_fallback(speakable_text)

            logger.info("TTS playback complete")

        except Exception as e:
            logger.error(f"TTS playback failed: {e}")
            self._emit(VoiceError(error=str(e), exception=e))

        finally:
            if self._state == VoiceState.SPEAKING:
                self._transition_to(VoiceState.IDLE)

    def _synthesize_with_fallback(self, text: str) -> None:
        """Synthesize and play text, falling back to next TTS if current fails.

        Args:
            text: Text to synthesize and play.

        Raises:
            RuntimeError: If all TTS backends fail.
        """
        tts_modules = self._tts_modules
        backend_names = getattr(self, "_tts_backend_names", None) or (
            [] if self._active_tts_backend is None else [self._active_tts_backend]
        )
        tried: list[str] = []
        last_error: Exception | None = None

        for name in backend_names:
            if name in tried:
                continue
            tried.append(name)

            # If we need to switch backends, initialize the new one
            if self._active_tts_backend != name or self._tts is None:
                tts_cls = tts_modules.get(name)
                if not tts_cls:
                    continue

                # Check health before trying to init
                if not tts_cls.is_healthy():
                    msg = tts_cls.health_check_error() or f"TTS '{name}' unhealthy"
                    logger.warning(f"Skipping TTS fallback '{name}': {msg}")
                    continue

                try:
                    backend_settings = self._get_backend_settings("tts", name)
                    self._tts = tts_cls(**backend_settings)
                    self._audio_player = AudioPlayer(sample_rate=self._tts.sample_rate)
                    self._active_tts_backend = name
                    logger.info(f"TTS fallback to: {name}")
                except Exception as e:
                    last_error = e
                    logger.warning(f"TTS fallback '{name}' init failed: {e}")
                    self._tts = None
                    continue

            # Attempt synthesis with current backend
            try:
                for chunk in self._tts.synthesize_stream(text):
                    if self._state != VoiceState.SPEAKING:
                        self._audio_player.stop()
                        return
                    self._audio_player.play(
                        chunk.audio,
                        sample_rate=chunk.sample_rate,
                        blocking=True,
                    )
                return  # Success
            except Exception as e:
                last_error = e
                logger.error(f"TTS backend '{name}' synthesis failed: {e}")
                self._emit(VoiceError(error=str(e), exception=e))
                self._tts = None  # Force re-init on next attempt

        # All backends failed
        raise RuntimeError(
            f"All TTS backends failed. Tried: {tried}. Last error: {last_error}"
        )

    def _watchdog_loop(self) -> None:
        """Watchdog thread: detect and recover from stuck LISTENING state.

        If we're in LISTENING but haven't received frames for too long,
        the audio stream likely died. Emit an error and return to IDLE.
        """
        while not self._watchdog_stop.wait(timeout=1.0):
            if self._state != VoiceState.LISTENING:
                continue

            now = time.time()

            if self._last_frame_time != 0:
                elapsed = now - self._last_frame_time
                reason = f"No audio frames for {elapsed:.1f}s"
            else:
                # If LISTENING started but we never received a frame, we still
                # need to fail loudly. Use recording_start_time as fallback.
                elapsed = now - self._recording_start_time
                reason = f"No audio frames received for {elapsed:.1f}s"

            if elapsed > self._frame_timeout:
                logger.error(
                    f"Watchdog: {reason} while LISTENING. "
                    "Audio stream may have died or microphone is unavailable."
                )
                self._emit(VoiceError(
                    error="Audio stream stopped unexpectedly. "
                          "Check microphone connection.",
                ))
                # Force transition back to IDLE
                try:
                    self._transition_to(VoiceState.IDLE)
                except VoiceStateError:
                    with self._state_lock:
                        self._state = VoiceState.IDLE
                self._recording_buffer.clear()
                self._last_frame_time = 0

    def _speak_loop(self) -> None:
        """Speaking worker that serializes TTS playback.

        This avoids one-thread-per-speak and guarantees ordering for queued
        speech requests.
        """
        while not self._speak_stop.is_set():
            try:
                text = self._speak_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                self._speak_response(text)
            except Exception as e:
                logger.error(f"Speak loop error: {e}")
                self._emit(VoiceError(error=str(e), exception=e))


# =============================================================================
# Backwards Compatibility Alias
# =============================================================================

# VoiceController is kept as an alias for backwards compatibility
VoiceController = VoiceCore

# Also re-export event using old name for backwards compatibility
VoiceStatusChanged = VoiceStateChanged
