"""Settings schema definitions for auto-rendering UIs.

This module provides the schema types that allow UIs to automatically
render settings forms from a declarative configuration.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, List, Literal, Optional


class FieldType(Enum):
    """Types of setting fields for UI rendering.

    Attributes:
        TEXT: Simple text input.
        PASSWORD: Masked text input, typically stored in .env.
        NUMBER: Numeric input (int or float based on default).
        CHECKBOX: Boolean toggle.
        SELECT: Dropdown with static options.
        DYNAMIC_SELECT: Dropdown populated at runtime via options_provider.
        ACTION: Button that triggers a flow (e.g., OAuth).
        MULTILINE: Multi-line text input (textarea).
    """

    TEXT = "text"
    PASSWORD = "password"
    NUMBER = "number"
    CHECKBOX = "checkbox"
    SELECT = "select"
    DYNAMIC_SELECT = "dynamic_select"
    ACTION = "action"
    MULTILINE = "multiline"
    PROVIDER_SELECT = "provider_select"


@dataclass
class SettingField:
    """Definition of a single setting field for UI rendering.

    Attributes:
        key: Dot-separated path to the setting (e.g., "hub.url").
        label: Human-readable label for the UI.
        type: Field type determining widget rendering.
        default: Default value if not set.
        description: Help text shown in UI tooltips.
        options: Static list of options for SELECT type.
        options_provider: Method name to call for DYNAMIC_SELECT options.
        action: Method name to call for ACTION type.
        secret: If True, store in .env instead of config.yaml.
        group: Grouping key for UI organization.
        depends_on: Only show if this key has a truthy value.
        validation: Optional validation function returning bool or error message.
        min_value: Minimum value for NUMBER type.
        max_value: Maximum value for NUMBER type.
        placeholder: Placeholder text for text inputs.
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
    validation: Optional[Callable[[Any], bool | str]] = field(
        default=None, repr=False
    )
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    placeholder: Optional[str] = None
    env_key: Optional[str] = None  # Explicit env var name for secrets
    provider_type: Optional[str] = None  # Type of provider (stt, tts) for PROVIDER_SELECT

    def __post_init__(self):
        """Validate field configuration."""
        if self.type == FieldType.SELECT and not self.options:
            raise ValueError(f"Field '{self.key}': SELECT type requires options")
        if self.type == FieldType.DYNAMIC_SELECT and not self.options_provider:
            raise ValueError(
                f"Field '{self.key}': DYNAMIC_SELECT type requires options_provider"
            )
        if self.type == FieldType.ACTION and not self.action:
            raise ValueError(f"Field '{self.key}': ACTION type requires action")

    def validate(self, value: Any) -> Optional[str]:
        """Validate a value against this field's constraints.

        Args:
            value: The value to validate.

        Returns:
            Error message if invalid, None if valid.
        """
        # Type-specific validation
        if self.type == FieldType.NUMBER and value is not None:
            try:
                num_value = float(value)
                if self.min_value is not None and num_value < self.min_value:
                    return f"{self.label} must be at least {self.min_value}"
                if self.max_value is not None and num_value > self.max_value:
                    return f"{self.label} must be at most {self.max_value}"
            except (TypeError, ValueError):
                return f"{self.label} must be a number"

        if self.type == FieldType.SELECT and self.options:
            if value is not None and value not in self.options:
                return f"{self.label} must be one of: {', '.join(self.options)}"

        # Custom validation
        if self.validation and value is not None:
            try:
                result = self.validation(value)
                if isinstance(result, str):
                    return result
                if not result:
                    return f"Invalid value for {self.label}"
            except Exception as e:
                return str(e)

        return None


@dataclass
class ActionResult:
    """Result from executing a settings action.

    Attributes:
        type: Action type determining UI behavior.
        url: URL to open for "open_browser" type.
        message: Message to display to user.
        pending: If True, UI should wait for a follow-up event.
        data: Additional data for the action.
    """

    type: Literal["open_browser", "show_dialog", "success", "error"]
    url: Optional[str] = None
    message: str = ""
    pending: bool = False
    data: Optional[dict] = None


def get_field_by_key(
    schema: List[SettingField], key: str
) -> Optional[SettingField]:
    """Find a field in a schema by its key.

    Args:
        schema: List of SettingField objects.
        key: The key to search for.

    Returns:
        The matching SettingField or None.
    """
    for setting_field in schema:
        if setting_field.key == key:
            return setting_field
    return None


def group_fields(schema: List[SettingField]) -> dict[str, List[SettingField]]:
    """Group fields by their group attribute.

    Args:
        schema: List of SettingField objects.

    Returns:
        Dictionary mapping group names to lists of fields.
    """
    groups: dict[str, List[SettingField]] = {}
    for setting_field in schema:
        if setting_field.group not in groups:
            groups[setting_field.group] = []
        groups[setting_field.group].append(setting_field)
    return groups
