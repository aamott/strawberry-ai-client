"""Configuration management for Strawberry AI.

.. deprecated::
    This module is deprecated in favor of the new SettingsManager system.
    New code should use::

        from strawberry.shared.settings import SettingsManager

        settings = SettingsManager(config_dir=Path("config"))
        value = settings.get("spoke_core", "hub.url")

    The old Settings Pydantic model and load_config() are maintained for
    backward compatibility but will be removed in a future version.

    Migration guide:
    - Old: config/settings.py (Pydantic models) + config/loader.py
    - New: shared/settings/manager.py (SettingsManager)

    Configuration files:
    - Old: src/config/config.yaml (flat structure)
    - New: config/settings.yaml (namespaced by module)
    - Secrets: .env (unchanged, used by both systems)
"""

from .loader import get_settings, load_config
from .settings import (
    AudioSettings,
    HubSettings,
    Settings,
    STTSettings,
    TTSSettings,
    VADSettings,
    WakeWordSettings,
)

__all__ = [
    "Settings",
    "AudioSettings",
    "WakeWordSettings",
    "VADSettings",
    "STTSettings",
    "TTSSettings",
    "HubSettings",
    "load_config",
    "get_settings",
]
