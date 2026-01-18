"""Settings schema definitions for auto-rendering UIs.

This module provides the schema types that allow UIs to automatically
render settings forms from a declarative configuration.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, List, Optional


class FieldType(Enum):
    """Types of setting fields for UI rendering.
    
    TEXT: Simple text input
    PASSWORD: Masked text input, typically stored in .env
    NUMBER: Numeric input (int or float)
    CHECKBOX: Boolean toggle
    SELECT: Dropdown with static options
    DYNAMIC_SELECT: Dropdown populated at runtime via options_provider
    ACTION: Button that triggers a flow (e.g., OAuth)
    """
    TEXT = "text"
    PASSWORD = "password"
    NUMBER = "number"
    CHECKBOX = "checkbox"
    SELECT = "select"
    DYNAMIC_SELECT = "dynamic_select"
    ACTION = "action"


@dataclass
class SettingField:
    """Definition of a single setting field for UI rendering.
    
    Attributes:
        key: Dot-separated path to the setting (e.g., "hub.url")
        label: Human-readable label for the UI
        type: Field type determining widget rendering
        default: Default value if not set
        description: Help text shown in UI
        options: Static list of options for SELECT type
        options_provider: Method name to call for DYNAMIC_SELECT options
        action: Method name to call for ACTION type
        secret: If True, store in .env instead of config.yaml
        group: Grouping key for UI organization
        depends_on: Only show if this key has a truthy value
        validation: Optional validation function
    """
    key: str
    label: str
    type: FieldType
    default: Any = None
    description: str = ""
    options: Optional[List[str]] = None
    options_provider: Optional[str] = None
    action: Optional[str] = None
    secret: bool = False
    group: str = "general"
    depends_on: Optional[str] = None
    validation: Optional[Callable[[Any], bool]] = field(default=None, repr=False)

    def __post_init__(self):
        """Validate field configuration."""
        if self.type == FieldType.SELECT and not self.options:
            raise ValueError(f"Field '{self.key}': SELECT type requires options")
        if self.type == FieldType.DYNAMIC_SELECT and not self.options_provider:
            raise ValueError(f"Field '{self.key}': DYNAMIC_SELECT type requires options_provider")
        if self.type == FieldType.ACTION and not self.action:
            raise ValueError(f"Field '{self.key}': ACTION type requires action")


@dataclass
class ActionResult:
    """Result from executing a settings action.
    
    Attributes:
        type: Action type ("open_browser", "show_dialog", "success", "error")
        url: URL to open for "open_browser" type
        message: Message to display to user
        pending: If True, UI should wait for a follow-up event
    """
    type: str  # "open_browser", "show_dialog", "success", "error"
    url: Optional[str] = None
    message: str = ""
    pending: bool = False


# Core settings schema - shared by all UIs
CORE_SETTINGS_SCHEMA: List[SettingField] = [
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
]


def get_field_by_key(schema: List[SettingField], key: str) -> Optional[SettingField]:
    """Find a field in a schema by its key.
    
    Args:
        schema: List of SettingField objects
        key: The key to search for
        
    Returns:
        The matching SettingField or None
    """
    for field in schema:
        if field.key == key:
            return field
    return None


def group_fields(schema: List[SettingField]) -> dict[str, List[SettingField]]:
    """Group fields by their group attribute.
    
    Args:
        schema: List of SettingField objects
        
    Returns:
        Dictionary mapping group names to lists of fields
    """
    groups: dict[str, List[SettingField]] = {}
    for setting_field in schema:
        if setting_field.group not in groups:
            groups[setting_field.group] = []
        groups[setting_field.group].append(setting_field)
    return groups
