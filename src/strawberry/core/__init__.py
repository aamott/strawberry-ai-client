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
)
from .session import ChatSession
from .settings_schema import (
    ActionResult,
    CORE_SETTINGS_SCHEMA,
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
    # Settings schema
    "SettingField",
    "FieldType",
    "ActionResult",
    "CORE_SETTINGS_SCHEMA",
    "get_field_by_key",
    "group_fields",
]
