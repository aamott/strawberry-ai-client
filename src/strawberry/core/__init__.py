"""Core module - single backend interface for all UIs."""

from .app import SpokeCore
from .events import (
    CoreError,
    CoreEvent,
    CoreReady,
    MessageAdded,
    SettingsChanged,
    ToolCallResult,
    ToolCallStarted,
    VoiceStatusChanged,
)
from .session import ChatSession
from .settings_schema import (
    CORE_SETTINGS_SCHEMA,
    ActionResult,
    FieldType,
    SettingField,
    get_field_by_key,
    group_fields,
)

__all__ = [
    # Core classes
    "SpokeCore",
    "ChatSession",
    # Events
    "CoreEvent",
    "MessageAdded",
    "ToolCallStarted",
    "ToolCallResult",
    "CoreReady",
    "CoreError",
    "SettingsChanged",
    "VoiceStatusChanged",
    # Settings schema
    "SettingField",
    "FieldType",
    "ActionResult",
    "CORE_SETTINGS_SCHEMA",
    "get_field_by_key",
    "group_fields",
]
