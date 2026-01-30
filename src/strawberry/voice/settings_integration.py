"""Voice settings helper.

Handles integration with SettingsManager: registration, validation, and sync.
"""

from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Sequence

from .component_manager import VoiceComponentManager
from .config import VoiceConfig

if TYPE_CHECKING:
    from strawberry.shared.settings import SettingsManager


class VoiceSettingsHelper:
    """Helper for managing voice settings."""

    def __init__(
        self,
        config: VoiceConfig,
        settings_manager: Optional["SettingsManager"],
        component_manager: VoiceComponentManager,
        on_change_callback: Callable[[str], None],
    ):
        """Initialize settings helper.

        Args:
            config: The VoiceConfig object to update.
            settings_manager: The SettingsManager instance.
            component_manager: The VoiceComponentManager (for backend discovery).
            on_change_callback: Callback(changed_type) to trigger re-init in Core.
                                changed_type is "stt", "tts", "vad", "wakeword".
        """
        self._config = config
        self._settings_manager = settings_manager
        self._component_manager = component_manager
        self._on_change = on_change_callback

    def register(self) -> None:
        """Register everything with SettingsManager."""
        if not self._settings_manager:
            return

        from .settings_schema import VOICE_CORE_SCHEMA

        # 1. Register voice_core namespace
        if not self._settings_manager.is_registered("voice_core"):
            self._settings_manager.register(
                namespace="voice_core",
                display_name="Voice",
                schema=VOICE_CORE_SCHEMA,
                order=20,
            )
            # Sync to config
            self._sync_config_from_manager()

        # 2. Register backend namespaces
        self._register_backend_namespaces()

        # 3. Register validators
        self._settings_manager.register_validator(
            "voice_core", "tts.order", self._validate_tts_order
        )

        # 4. Listen for changes
        self._settings_manager.on_change(self._handle_settings_change)

    def _sync_config_from_manager(self) -> None:
        """Sync VoiceConfig FROM SettingsManager (and write defaults if missing)."""
        cfg = self._config

        def to_order_string(val: str | Sequence[str]) -> str:
            if isinstance(val, str):
                return val
            return ",".join(val)

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
                self._update_config_value(key, existing)
            else:
                self._settings_manager.set(
                    "voice_core", key, default_value, skip_validation=True
                )

    def _update_config_value(self, key: str, value: Any) -> None:
        """Update a single config value."""
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
            cfg.stt_backend = value if value else "leopard"
        elif key == "tts.order":
            cfg.tts_backend = value if value else "pocket"
        elif key == "vad.order":
            cfg.vad_backend = value if value else "silero"
        elif key == "wakeword.order":
            cfg.wake_backend = value if value else "porcupine"

    def _register_backend_namespaces(self) -> None:
        """Register settings for discovered backends."""
        data = self._component_manager.get_discovered_modules()

        # Helper to register a dict of modules
        def reg(modules: Dict[str, Any], type_: str, label_prefix: str):
            for name, cls in modules.items():
                namespace = f"voice.{type_}.{name}"
                if not self._settings_manager.is_registered(namespace):
                    schema = cls.get_settings_schema()
                    if schema:
                        self._settings_manager.register(
                            namespace=namespace,
                            display_name=f"{label_prefix}: {cls.name}",
                            schema=schema,
                            order=100,
                        )

        reg(data["stt"], "stt", "STT")
        reg(data["tts"], "tts", "TTS")
        reg(data["vad"], "vad", "VAD")
        reg(data["wakeword"], "wakeword", "Wake")

    def _validate_tts_order(self, value: Any) -> Optional[str]:
        if not value:
            return "TTS order cannot be empty"
        if isinstance(value, str):
            items = [x.strip() for x in value.split(",") if x.strip()]
        elif isinstance(value, (list, tuple)):
            items = list(value)
        else:
            return "Invalid format"

        if not items:
            return "TTS order cannot be empty"
        return None

    def _handle_settings_change(self, namespace: str, key: str, value: Any) -> None:
        """Handle settings change event."""
        if not namespace.startswith("voice"):
            return

        # 1. Voice Core main settings
        if namespace == "voice_core":
            self._update_config_value(key, value)

            # Map key to module type for re-init
            if key == "stt.order":
                self._on_change("stt")
            elif key == "tts.order":
                self._on_change("tts")
            elif key == "vad.order":
                self._on_change("vad")
            elif key == "wakeword.order":
                self._on_change("wakeword")

        # 2. Backend specific settings (voice.stt.leopard etc)
        elif namespace.startswith("voice.stt."):
            name = namespace.split(".")[2]
            if name == self._component_manager.active_stt_backend:
                self._on_change("stt")
        elif namespace.startswith("voice.tts."):
            name = namespace.split(".")[2]
            if name == self._component_manager.active_tts_backend:
                self._on_change("tts")
        elif namespace.startswith("voice.vad."):
            name = namespace.split(".")[2]
            if name == self._component_manager.active_vad_backend:
                self._on_change("vad")
        elif namespace.startswith("voice.wakeword."):
            name = namespace.split(".")[3] if len(namespace.split(".")) > 3 else ""
            if name == self._component_manager.active_wake_backend:
                self._on_change("wakeword")
