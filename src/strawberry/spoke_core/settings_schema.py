"""Settings schema definitions for SpokeCore.

This module defines the SPOKE_CORE_SCHEMA for SpokeCore settings.
The core types (FieldType, SettingField, ActionResult) are imported
from the shared settings package.

For backward compatibility, the types are re-exported from this module.
"""

from typing import List

# Import from shared settings package
from strawberry.shared.settings import (
    ActionResult,
    FieldType,
    SettingField,
    get_field_by_key,
    group_fields,
)

# Re-export for backward compatibility
__all__ = [
    "FieldType",
    "SettingField",
    "ActionResult",
    "SPOKE_CORE_SCHEMA",
    "get_field_by_key",
    "group_fields",
]

# Spoke Core settings schema
SPOKE_CORE_SCHEMA: List[SettingField] = [
    # General
    SettingField(
        key="device.name",
        label="Device Name",
        type=FieldType.TEXT,
        default="Strawberry Spoke",
        description="Name of this device shown in Hub",
        group="general",
    ),

    # Hub connection
    SettingField(
        key="hub.url",
        label="Hub URL",
        type=FieldType.TEXT,
        default="http://localhost:8000",
        description="URL of the central Hub",
        group="hub",
        metadata={
            "help_text": (
                "The address of the central AI Hub instance.\n"
                "If running locally, use http://localhost:8000.\n"
                "If on a network, use http://<hub-ip>:8000."
            )
        },
    ),
    SettingField(
        key="hub.token",
        label="Hub Token",
        type=FieldType.PASSWORD,
        secret=True,
        description="Authentication token for Hub connection",
        group="hub",
        env_key="HUB_DEVICE_TOKEN",  # Legacy env var name for TensorZero compat
    ),
    SettingField(
        key="hub.connect",
        label="Connect to Hub",
        type=FieldType.ACTION,
        action="hub_oauth",
        description="Launch browser to authenticate with Hub",
        group="hub",
    ),
    SettingField(
        key="hub.log_ping_pong",
        label="Log Hub WebSocket Ping/Pong",
        type=FieldType.CHECKBOX,
        default=False,
        description="Enable verbose logging of Hub WebSocket ping/pong frames",
        group="hub",
        metadata={
            "help_text": (
                "When enabled, WebSocket ping/pong frames are logged at DEBUG.\n"
                "Keep disabled to reduce log noise during normal operation."
            )
        },
    ),

    # Offline LLM
    SettingField(
        key="local_llm.model",
        label="Offline Model",
        type=FieldType.DYNAMIC_SELECT,
        options_provider="get_available_models",
        default="llama3.2:3b",
        description="Model to use when offline",
        group="offline",
        metadata={
            "help_text": (
                "The Ollama model to use when the Hub is unreachable.\n"
                "Ensure this model is pulled in Ollama:\n"
                "ollama pull llama3.2:3b"
            )
        },
    ),
    SettingField(
        key="local_llm.enabled",
        label="Enable Offline Mode",
        type=FieldType.CHECKBOX,
        default=True,
        description="Allow running without Hub connection",
        group="offline",
    ),

    # Skills
    SettingField(
        key="skills.allow_unsafe_exec",
        label="Allow Unsafe Skill Execution",
        type=FieldType.CHECKBOX,
        default=False,
        description="Allow skills to run code directly outside the sandbox (security risk)",
        group="skills",
    ),
    SettingField(
        key="skills.path",
        label="Skills Directory",
        type=FieldType.TEXT,
        default="skills",
        description="Path to directory containing user skills",
        group="skills",
    ),

    # Storage
    SettingField(
        key="storage.db_path",
        label="Database Path",
        type=FieldType.TEXT,
        default="data/sessions.db",
        description="Path to local session storage database",
        group="storage",
    ),

    # TensorZero
    SettingField(
        key="tensorzero.enabled",
        label="Enable TensorZero",
        type=FieldType.CHECKBOX,
        default=True,
        description="Use TensorZero for LLM routing and fallback",
        group="tensorzero",
    ),

    # LLM Settings
    SettingField(
        key="llm.temperature",
        label="Temperature",
        type=FieldType.NUMBER,
        default=0.7,
        description="LLM temperature (0.0-2.0, higher = more creative)",
        group="llm",
        metadata={
            "help_text": (
                "Controls randomness of the output.\n"
                "0.0 = Deterministic, focused.\n"
                "0.7 = Balanced.\n"
                "1.0+ = Creative, unpredictable."
            )
        },
    ),

    # Conversation
    SettingField(
        key="conversation.max_history",
        label="Max History",
        type=FieldType.NUMBER,
        default=20,
        description="Maximum conversation messages to keep in memory",
        group="conversation",
    ),

    # Testing
    SettingField(
        key="testing.deterministic_tool_hooks",
        label="Deterministic Tool Hooks",
        type=FieldType.CHECKBOX,
        default=False,
        description="Enable deterministic tool hooks for testing",
        group="testing",
        metadata={
            "help_text": (
                "When enabled, specific phrases trigger immediate tool execution:\n"
                "- 'use search_skills' -> runs search_skills\n"
                "- 'must use python_exec' with device.* -> runs python_exec\n"
                "This makes tool-use tests deterministic."
            )
        },
    ),

    # UI Settings
    SettingField(
        key="ui.theme",
        label="Theme",
        type=FieldType.SELECT,
        options=["dark", "light"],
        default="dark",
        description="Application color theme",
        group="ui",
    ),
    SettingField(
        key="ui.start_minimized",
        label="Start Minimized",
        type=FieldType.CHECKBOX,
        default=False,
        description="Start application minimized to system tray",
        group="ui",
    ),
    SettingField(
        key="ui.show_waveform",
        label="Show Waveform",
        type=FieldType.CHECKBOX,
        default=True,
        description="Display audio waveform during voice input",
        group="ui",
    ),
]


# Alias for backward compatibility
CORE_SETTINGS_SCHEMA = SPOKE_CORE_SCHEMA
