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
    ),
    SettingField(
        key="hub.token",
        label="Hub Token",
        type=FieldType.PASSWORD,
        secret=True,
        description="Authentication token for Hub connection",
        group="hub",
    ),
    SettingField(
        key="hub.connect",
        label="Connect to Hub",
        type=FieldType.ACTION,
        action="hub_oauth",
        description="Launch browser to authenticate with Hub",
        group="hub",
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
]


# Alias for backward compatibility
CORE_SETTINGS_SCHEMA = SPOKE_CORE_SCHEMA
