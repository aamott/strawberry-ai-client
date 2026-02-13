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
SCHEMA_VERSION = 3

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
    "SKILLS_CONFIG_SCHEMA",
    "register_skills_config_schema",
]

# Skills configuration (registered on the Skills tab)
SKILLS_CONFIG_SCHEMA: List[SettingField] = [
    SettingField(
        key="path",
        label="Skills Directory",
        type=FieldType.DIRECTORY_PATH,
        default="skills",
        description="Path to directory containing user skills",
        group="general",
    ),
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

# Keys removed in v3 (moved to tensorzero namespace / removed)
_V2_DEAD_KEYS = frozenset({
    "local_llm.url",
    "local_llm.model",
    "local_llm.enabled",
    "skills.path",  # Moved to skills_config namespace
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


def _migrate_v2_to_v3(values: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate spoke_core settings from schema v2 to v3.

    Changes:
    - Remove local_llm.* keys (moved to tensorzero namespace).
    - Remove skills.path (moved to skills_config namespace).
    """
    for key in _V2_DEAD_KEYS:
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

    # Register migrations before register() triggers them
    settings.register_migration(
        "spoke_core", from_version=1, to_version=2, migrator=_migrate_v1_to_v2
    )
    settings.register_migration(
        "spoke_core", from_version=2, to_version=3, migrator=_migrate_v2_to_v3
    )
    # Also handle fresh installs (version 0 → 1) by chaining through v1
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


def register_skills_config_schema(settings: "SettingsManager") -> None:
    """Register skills_config namespace on the Skills tab.

    Args:
        settings: The SettingsManager instance.
    """
    if settings.is_registered("skills_config"):
        return

    settings.register(
        namespace="skills_config",
        display_name="Skills Configuration",
        schema=SKILLS_CONFIG_SCHEMA,
        order=5,  # Before per-skill settings (50+)
        tab="Skills",
    )
