"""Settings schema definitions for SpokeCore.

This module defines the SPOKE_CORE_SCHEMA for SpokeCore settings.
The core types (FieldType, SettingField, ActionResult) are imported
from the shared settings package.

For backward compatibility, the types are re-exported from this module.
"""

from typing import TYPE_CHECKING, Any, Dict, List

# Import from shared settings package
from strawberry.shared.settings import (
    ActionResult,
    FieldType,
    SettingField,
    get_field_by_key,
    group_fields,
)
from strawberry.skills.prompt import DEFAULT_SYSTEM_PROMPT_TEMPLATE

if TYPE_CHECKING:
    from strawberry.shared.settings import SettingsManager

# Schema version — bump when schema changes require migration
SCHEMA_VERSION = 2

# Re-export for backward compatibility
__all__ = [
    "FieldType",
    "SettingField",
    "ActionResult",
    "SPOKE_CORE_SCHEMA",
    "SCHEMA_VERSION",
    "get_field_by_key",
    "group_fields",
    "register_spoke_core_schema",
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
    # Hub connection timeout
    SettingField(
        key="hub.timeout_seconds",
        label="Hub Timeout (seconds)",
        type=FieldType.NUMBER,
        default=30,
        description="Timeout in seconds for Hub HTTP requests",
        group="hub",
        min_value=5,
        max_value=300,
        metadata={
            "help_text": (
                "How long to wait for Hub HTTP API responses.\n"
                "Increase if on a slow network. Decrease for faster\n"
                "failure detection."
            )
        },
    ),
    # Offline LLM
    SettingField(
        key="local_llm.url",
        label="Ollama URL",
        type=FieldType.TEXT,
        default="http://localhost:11434/v1",
        description="URL for the local Ollama API",
        group="offline",
        metadata={
            "help_text": (
                "Base URL for the local Ollama instance.\n"
                "Default is http://localhost:11434/v1.\n"
                "Change if Ollama is running on a different host/port."
            )
        },
    ),
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
        key="skills.sandbox.enabled",
        label="Enable Sandbox",
        type=FieldType.CHECKBOX,
        default=True,
        description="Run LLM-generated code in a secure sandbox",
        group="skills",
        metadata={
            "help_text": (
                "When enabled, LLM-generated code runs in a restricted\n"
                "sandbox (RestrictedPython). Disabling allows direct\n"
                "Python execution — use with caution."
            )
        },
    ),
    SettingField(
        key="skills.allow_unsafe_exec",
        label="Allow Unsafe Skill Execution",
        type=FieldType.CHECKBOX,
        default=False,
        description=(
            "Allow skills to run code directly outside the sandbox (security risk)"
        ),
        group="skills",
    ),
    SettingField(
        key="skills.path",
        label="Skills Directory",
        type=FieldType.DIRECTORY_PATH,
        default="skills",
        description="Path to directory containing user skills",
        group="skills",
    ),
    # LLM Settings
    SettingField(
        key="llm.system_prompt",
        label="System Prompt",
        type=FieldType.MULTILINE,
        default=DEFAULT_SYSTEM_PROMPT_TEMPLATE,
        description="System prompt template for the LLM",
        group="llm",
        metadata={
            "help_text": (
                "The system prompt sent to the LLM in offline mode.\n"
                "Use {skill_descriptions} as a placeholder for the\n"
                "auto-generated list of loaded skills.\n\n"
                "Reset to the built-in default by clearing this field."
            ),
            "rows": 12,
        },
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
]


# Alias for backward compatibility
CORE_SETTINGS_SCHEMA = SPOKE_CORE_SCHEMA

# Keys removed in v2 (dead settings that were never wired up)
_V1_DEAD_KEYS = frozenset({
    "tensorzero.enabled",
    "storage.db_path",
    "conversation.max_history",
    "llm.temperature",
    "ui.theme",
    "ui.start_minimized",
    "ui.show_waveform",
})


def _migrate_v1_to_v2(values: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate spoke_core settings from schema v1 to v2.

    Changes:
    - Replace empty llm.system_prompt with the default template.
    - Remove dead keys that were never wired to code.
    """
    # Replace empty system prompt with the actual default
    prompt = values.get("llm.system_prompt", "")
    if not prompt or not prompt.strip():
        values["llm.system_prompt"] = DEFAULT_SYSTEM_PROMPT_TEMPLATE

    # Remove dead keys
    for key in _V1_DEAD_KEYS:
        values.pop(key, None)

    return values


def register_spoke_core_schema(settings: "SettingsManager") -> None:
    """Register spoke_core namespace with migrations.

    Call this instead of ``settings.register()`` directly so that
    migrations are applied before the schema is registered.

    Args:
        settings: The SettingsManager instance.
    """
    if settings.is_registered("spoke_core"):
        return

    # Register migration before register() triggers it
    settings.register_migration(
        "spoke_core", from_version=1, to_version=2, migrator=_migrate_v1_to_v2
    )
    # Also handle fresh installs (version 0 → 2) by chaining through v1
    settings.register_migration(
        "spoke_core",
        from_version=0,
        to_version=1,
        migrator=lambda v: v,  # no-op, fresh installs get defaults
    )

    settings.register(
        namespace="spoke_core",
        display_name="Spoke Core",
        schema=SPOKE_CORE_SCHEMA,
        order=10,
        tab="General",
        schema_version=SCHEMA_VERSION,
    )
