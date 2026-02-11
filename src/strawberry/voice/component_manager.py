"""Voice component manager.

Manages the lifecycle, discovery, and configuration of voice pipeline components:
STT, TTS, VAD, Wake Word, and Audio Stream.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Set, Type

from .audio.backends.sounddevice_backend import SoundDeviceBackend
from .audio.playback import AudioPlayer
from .audio.stream import AudioStream
from .config import VoiceConfig
from .stt import STTEngine, discover_stt_modules
from .tts import TTSEngine, discover_tts_modules
from .vad import VADBackend, VADProcessor, discover_vad_modules
from .wakeword import WakeWordDetector, discover_wake_modules

if TYPE_CHECKING:
    from strawberry.shared.settings import SettingsManager

logger = logging.getLogger(__name__)


@dataclass
class VoiceComponents:
    """Active voice components."""

    stt: Optional[STTEngine] = None
    tts: Optional[TTSEngine] = None
    vad: Optional[VADBackend] = None
    wake: Optional[WakeWordDetector] = None
    audio_stream: Optional[AudioStream] = None
    vad_processor: Optional[VADProcessor] = None
    audio_player: Optional[AudioPlayer] = None
    audio_backend: Optional[SoundDeviceBackend] = None


class VoiceComponentManager:
    """Manages voice pipeline components."""

    def __init__(
        self,
        config: VoiceConfig,
        settings_manager: Optional["SettingsManager"] = None,
    ):
        """Initialize manager."""
        self._config = config
        self._settings_manager = settings_manager

        # TTS init error details (backend name -> reason). Used to provide
        # user-facing error messages when all backends fail.
        self._tts_init_errors: Dict[str, str] = {}

        # Active components container
        self.components = VoiceComponents()

        # Discovery caches
        self._stt_modules: Dict[str, Type[STTEngine]] = {}
        self._tts_modules: Dict[str, Type[TTSEngine]] = {}
        self._vad_modules: Dict[str, Type[VADBackend]] = {}
        self._wake_modules: Dict[str, Type[WakeWordDetector]] = {}

        # State tracking
        self.active_stt_backend: Optional[str] = None
        self.active_tts_backend: Optional[str] = None
        self.active_vad_backend: Optional[str] = None
        self.active_wake_backend: Optional[str] = None

        # Fallback lists
        self.stt_backend_names: List[str] = []
        self.tts_backend_names: List[str] = []

    def refresh_module_discovery(self) -> None:
        """Re-discover voice backend modules."""
        logger.info("Refreshing voice module discovery")
        self._stt_modules = discover_stt_modules()
        self._tts_modules = discover_tts_modules()
        self._vad_modules = discover_vad_modules()
        self._wake_modules = discover_wake_modules()

    def get_discovered_modules(self) -> Dict[str, Dict[str, Any]]:
        """Get all discovered modules."""
        if not self._stt_modules:
            self.refresh_module_discovery()

        return {
            "stt": self._stt_modules,
            "tts": self._tts_modules,
            "vad": self._vad_modules,
            "wakeword": self._wake_modules,
        }

    async def initialize(self) -> None:
        """Initialize all components."""
        # Ensure discovery
        if not self._stt_modules:
            self.refresh_module_discovery()

        # Parse config lists
        self.stt_backend_names = self._parse_backend_names(self._config.stt_backend)
        self.tts_backend_names = self._parse_backend_names(self._config.tts_backend)
        vad_backend_names = self._parse_backend_names(self._config.vad_backend)
        wake_backend_names = self._parse_backend_names(self._config.wake_backend)

        # 1. Initialize Wake Word (Optional)
        await self._init_wakeword(wake_backend_names)

        # 2. Initialize Audio Stream
        self._init_audio_stream()

        # 3. Initialize VAD (Required)
        await self._init_vad(vad_backend_names)

        # 4. Initialize STT (Required)
        await self._init_stt(self.stt_backend_names)

        # 5. Initialize TTS (Required)
        await self._init_tts(self.tts_backend_names)

    async def cleanup(self) -> None:
        """Cleanup all components."""
        if self.components.audio_stream:
            self.components.audio_stream.stop()
            self.components.audio_stream = None

        self.components.audio_backend = None

        if self.components.wake:
            self.components.wake.cleanup()
            self.components.wake = None

        if self.components.vad:
            self.components.vad.cleanup()
            self.components.vad = None

        if self.components.stt:
            self.components.stt.cleanup()
            self.components.stt = None

        if self.components.tts:
            self.components.tts.cleanup()
            self.components.tts = None

        self.active_stt_backend = None
        self.active_tts_backend = None
        self.active_vad_backend = None
        self.active_wake_backend = None

    # -------------------------------------------------------------------------
    # Individual Component Init
    # -------------------------------------------------------------------------

    async def _init_wakeword(self, backend_names: List[str]) -> None:
        """Initialize wake word detector."""
        errors = []
        for name in backend_names:
            cls = self._wake_modules.get(name)
            if not cls:
                errors.append(f"Backend '{name}' not found")
                continue

            try:
                settings = self._get_backend_settings("wakeword", name)
                self.components.wake = cls(
                    keywords=self._config.wake_words,
                    sensitivity=self._config.sensitivity,
                    **settings,
                )
                self.active_wake_backend = name
                logger.info(f"Wake backend selected: {name}")
                return
            except Exception as e:
                msg = f"Wake backend '{name}' init failed: {e}"
                logger.warning(msg)
                errors.append(msg)

        logger.warning(f"Wake word detection unavailable. Errors: {errors}")

    def _init_audio_stream(self) -> None:
        """Initialize audio stream based on wake word requirements or config."""
        if self.components.wake:
            wake_frame_len = self.components.wake.frame_length
            wake_sample_rate = self.components.wake.sample_rate
            frame_ms = max(1, int(wake_frame_len * 1000 / wake_sample_rate))
        else:
            wake_sample_rate = self._config.sample_rate
            frame_ms = 30

        self.components.audio_backend = SoundDeviceBackend(
            sample_rate=wake_sample_rate,
            frame_length_ms=frame_ms,
        )
        self.components.audio_stream = AudioStream(self.components.audio_backend)
        logger.info(f"Audio stream: {wake_sample_rate}Hz, {frame_ms}ms frames")

    async def _init_vad(self, backend_names: List[str]) -> None:
        """Initialize VAD."""
        errors = []
        for name in backend_names:
            cls = self._vad_modules.get(name)
            if not cls:
                errors.append(f"Backend '{name}' not found")
                continue

            try:
                settings = self._get_backend_settings("vad", name)
                # Must match audio stream sample rate
                rate = self.components.audio_backend.sample_rate
                self.components.vad = cls(sample_rate=rate, **settings)

                if hasattr(self.components.vad, "preload"):
                    logger.info("Preloading VAD model...")
                    self.components.vad.preload()

                from .vad.processor import VADConfig

                self.components.vad_processor = VADProcessor(
                    self.components.vad,
                    VADConfig(),
                    frame_duration_ms=self.components.audio_backend.frame_length_ms,
                )

                self.active_vad_backend = name
                logger.info(f"VAD backend selected: {name}")
                return
            except Exception as e:
                msg = f"VAD backend '{name}' init failed: {e}"
                logger.error(msg)
                errors.append(msg)

        raise RuntimeError(f"VAD initialization failed. Errors: {errors}")

    async def _init_stt(self, backend_names: List[str]) -> None:
        """Initialize STT."""
        errors = []
        for name in backend_names:
            try:
                self.init_stt_backend(name)
                return
            except Exception as e:
                msg = f"STT backend '{name}' init failed: {e}"
                logger.error(msg)
                errors.append(msg)

        raise RuntimeError(f"STT initialization failed. Errors: {errors}")

    def init_stt_backend(self, name: str) -> None:
        """Initialize a specific STT backend (used for fallback)."""
        cls = self._stt_modules.get(name)
        if not cls:
            raise RuntimeError(f"STT backend '{name}' not found")

        if self.components.stt:
            self.components.stt.cleanup()

        settings = self._get_backend_settings("stt", name)
        self.components.stt = cls(**settings)
        self.active_stt_backend = name
        logger.info(f"STT backend selected: {name}")

    async def _init_tts(self, backend_names: List[str]) -> None:
        """Initialize TTS."""
        errors: List[str] = []
        for name in backend_names:
            if await self.init_tts_backend(name):
                return

            # Prefer the most specific stored error, otherwise fall back.
            errors.append(self._tts_init_errors.get(name, f"TTS backend '{name}' failed"))

        raise RuntimeError(f"TTS initialization failed. Errors: {errors}")

    async def init_tts_backend(self, name: str) -> bool:
        """Initialize a specific TTS backend (used for fallback)."""
        cls = self._tts_modules.get(name)
        if not cls:
            self._tts_init_errors[name] = f"TTS backend '{name}' not found"
            return False

        if not cls.is_healthy():
            health_error = None
            if hasattr(cls, "health_check_error"):
                health_error = cls.health_check_error()
            msg = (
                f"TTS backend '{name}' skipped (unhealthy): {health_error}"
                if health_error
                else f"TTS backend '{name}' skipped (unhealthy)"
            )
            self._tts_init_errors[name] = msg
            logger.warning(msg)
            return False

        try:
            if self.components.tts:
                self.components.tts.cleanup()

            settings = self._get_backend_settings("tts", name)
            self.components.tts = cls(**settings)
            self.components.audio_player = AudioPlayer(
                sample_rate=self.components.tts.sample_rate
            )
            self.active_tts_backend = name
            logger.info(f"TTS backend selected: {name}")
            return True
        except Exception as e:
            msg = f"TTS backend '{name}' init failed: {e}"
            self._tts_init_errors[name] = msg
            logger.warning(msg)
            return False

    # -------------------------------------------------------------------------
    # Re-initialization (Hot Reload)
    # -------------------------------------------------------------------------

    async def reinitialize_pending(self, pending: Set[str]) -> bool:
        """Reinitialize backends that have pending changes."""
        success = True

        if "stt" in pending:
            # Refresh list
            self.stt_backend_names = self._parse_backend_names(self._config.stt_backend)
            # Try to re-init current or fallback
            try:
                # If current still in list, try to keep it
                # (or re-init it with new settings)
                target = self.active_stt_backend
                if not target or target not in self.stt_backend_names:
                    target = self.stt_backend_names[0] if self.stt_backend_names else None

                if target:
                    self.init_stt_backend(target)
                else:
                    success = False
            except Exception:
                # Fallback to full init loop
                try:
                    await self._init_stt(self.stt_backend_names)
                except Exception:
                    success = False

        if "tts" in pending:
            self.tts_backend_names = self._parse_backend_names(self._config.tts_backend)
            try:
                target = self.active_tts_backend
                if not target or target not in self.tts_backend_names:
                    target = self.tts_backend_names[0] if self.tts_backend_names else None

                if not target or not await self.init_tts_backend(target):
                    # Fallback loop
                    await self._init_tts(self.tts_backend_names)
            except Exception:
                success = False

        return success

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _get_backend_settings(self, type_: str, name: str) -> Dict[str, Any]:
        """Get settings for backend from manager."""
        if not self._settings_manager:
            return {}
        return self._settings_manager.get_all(f"voice.{type_}.{name}") or {}

    def _parse_backend_names(self, value: str | Sequence[str]) -> List[str]:
        """Normalize backend config value."""
        if isinstance(value, str):
            names = [part.strip() for part in value.split(",")]
            return [name for name in names if name]
        names = [str(item).strip() for item in value]
        return [name for name in names if name]

    def get_backend_health(self, type_: str, name: str) -> tuple[bool, str | None]:
        """Check if a backend is healthy.

        Args:
            type_: Backend type ("stt", "tts", "vad", "wakeword").
            name: Backend name (e.g., "whisper", "pocket").

        Returns:
            Tuple of (is_healthy, error_message).
        """
        modules = {
            "stt": self._stt_modules,
            "tts": self._tts_modules,
            "vad": self._vad_modules,
            "wakeword": self._wake_modules,
        }

        module_dict = modules.get(type_, {})
        if not module_dict:
            self.refresh_module_discovery()
            module_dict = modules.get(type_, {})

        cls = module_dict.get(name)
        if not cls:
            return False, f"Backend '{name}' not found"

        try:
            if hasattr(cls, "is_healthy") and not cls.is_healthy():
                error = (
                    cls.health_check_error()
                    if hasattr(cls, "health_check_error")
                    else None
                )
                return False, error or "Backend unavailable"
            return True, None
        except Exception as e:
            return False, str(e)

    def get_all_backend_health(self) -> Dict[str, Dict[str, tuple[bool, str | None]]]:
        """Get health status for all discovered backends.

        Returns:
            Dict mapping type -> name -> (is_healthy, error_message).
        """
        if not self._stt_modules:
            self.refresh_module_discovery()

        result: Dict[str, Dict[str, tuple[bool, str | None]]] = {}
        for type_, modules in [
            ("stt", self._stt_modules),
            ("tts", self._tts_modules),
            ("vad", self._vad_modules),
            ("wakeword", self._wake_modules),
        ]:
            result[type_] = {}
            for name in modules:
                result[type_][name] = self.get_backend_health(type_, name)

        return result
