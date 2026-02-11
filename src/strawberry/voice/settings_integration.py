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
                tab="Voice",
            )
            # Sync to config
            self._sync_config_from_manager()

        # 2. Register backend namespaces
        self._register_backend_namespaces()

        # 3. Register options providers for discovered backends
        self._register_backend_options_providers()

        # 4. Register validators
        self._settings_manager.register_validator(
            "voice_core", "tts.order", self._validate_tts_order
        )

        # 5. Listen for changes
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
                            tab="Voice",
                        )

        reg(data["stt"], "stt", "STT")
        reg(data["tts"], "tts", "TTS")
        reg(data["vad"], "vad", "VAD")
        reg(data["wakeword"], "wakeword", "Wake")

    def _register_backend_options_providers(self) -> None:
        """Register options providers that return discovered backend names.

        These providers allow the settings UI to get the list of available
        backends for PROVIDER_SELECT fields without requiring all backends
        to have registered namespaces.
        """
        data = self._component_manager.get_discovered_modules()

        # Create provider functions that return backend names
        def make_provider(modules: Dict[str, Any]):
            return lambda: list(modules.keys())

        self._settings_manager.register_options_provider(
            "available_stt_backends", make_provider(data["stt"])
        )
        self._settings_manager.register_options_provider(
            "available_tts_backends", make_provider(data["tts"])
        )
        self._settings_manager.register_options_provider(
            "available_vad_backends", make_provider(data["vad"])
        )
        self._settings_manager.register_options_provider(
            "available_wakeword_backends", make_provider(data["wakeword"])
        )

        # Register health check providers
        self._settings_manager.register_options_provider(
            "stt_backend_health",
            lambda: {
                name: self._component_manager.get_backend_health("stt", name)
                for name in data["stt"]
            },
        )
        self._settings_manager.register_options_provider(
            "tts_backend_health",
            lambda: {
                name: self._component_manager.get_backend_health("tts", name)
                for name in data["tts"]
            },
        )
        self._settings_manager.register_options_provider(
            "vad_backend_health",
            lambda: {
                name: self._component_manager.get_backend_health("vad", name)
                for name in data["vad"]
            },
        )
        self._settings_manager.register_options_provider(
            "wakeword_backend_health",
            lambda: {
                name: self._component_manager.get_backend_health("wakeword", name)
                for name in data["wakeword"]
            },
        )

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

    # Maps voice_core key prefixes to module type for re-init
    _KEY_TO_MODULE: dict[str, str] = {
        "stt.order": "stt",
        "tts.order": "tts",
        "vad.order": "vad",
        "wakeword.order": "wakeword",
    }

    # Maps namespace prefixes to (module_type, active_backend_attr, name_index)
    _NS_PREFIX_MAP: list[tuple[str, str, str, int]] = [
        ("voice.stt.", "stt", "active_stt_backend", 2),
        ("voice.tts.", "tts", "active_tts_backend", 2),
        ("voice.vad.", "vad", "active_vad_backend", 2),
        ("voice.wakeword.", "wakeword", "active_wake_backend", 3),
    ]

    def _handle_settings_change(self, namespace: str, key: str, value: Any) -> None:
        """Handle settings change event."""
        if not namespace.startswith("voice"):
            return

        # 1. Voice Core main settings
        if namespace == "voice_core":
            self._update_config_value(key, value)
            module_type = self._KEY_TO_MODULE.get(key)
            if module_type:
                self._on_change(module_type)
            return

        # 2. Backend-specific settings (voice.stt.leopard etc)
        self._handle_backend_settings_change(namespace)

    def _handle_backend_settings_change(self, namespace: str) -> None:
        """Handle a change in a backend-specific namespace."""
        for prefix, module_type, attr, idx in self._NS_PREFIX_MAP:
            if namespace.startswith(prefix):
                parts = namespace.split(".")
                name = parts[idx] if len(parts) > idx else ""
                if name == getattr(self._component_manager, attr):
                    self._on_change(module_type)
                return
