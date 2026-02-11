"""Settings schema definitions for auto-rendering UIs.

This module provides the schema types that allow UIs to automatically
render settings forms from a declarative configuration.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, List, Literal, Optional


class ValidationMode(Enum):
    """When to run validation for a setting field.

    Attributes:
        ON_CHANGE: Validate immediately on every change (may be expensive).
        ON_BLUR: Validate when field loses focus (default, good balance).
        ON_SAVE: Validate only when user clicks Save.
        ASYNC: Validate in background with status indicator.
    """

    ON_CHANGE = "on_change"
    ON_BLUR = "on_blur"
    ON_SAVE = "on_save"
    ASYNC = "async"


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
        PROVIDER_SELECT: Dropdown that controls which sub-settings namespace to show.
        LIST: Ordered list of values (strings, numbers, or from preset options).
        FILE_PATH: File path with browse button.
        DIRECTORY_PATH: Directory path with browse button.
        COLOR: Color picker (hex value).
        SLIDER: Visual range slider (alternative to NUMBER).
        DATE: Date picker (ISO format).
        TIME: Time picker (HH:MM format).
        DATETIME: Combined date/time picker.
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
    LIST = "list"
    FILE_PATH = "file_path"
    DIRECTORY_PATH = "directory_path"
    COLOR = "color"
    SLIDER = "slider"
    DATE = "date"
    TIME = "time"
    DATETIME = "datetime"


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
    # Template for provider namespace (e.g. "voice.{provider_type}.{value}")
    provider_namespace_template: Optional[str] = None
    # Arbitrary metadata for UI hints (e.g., {"input_format": "json"})
    metadata: Optional[dict[str, Any]] = None
    # Validation timing control
    validation_mode: ValidationMode = ValidationMode.ON_BLUR
    # List constraints for LIST type fields
    list_item_type: Optional[str] = None  # "string", "number", or None (use options)
    min_items: Optional[int] = None  # Minimum number of items required
    max_items: Optional[int] = None  # Maximum number of items allowed
    allow_custom: bool = True  # Can user add custom values not in options?

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
        if self.type in (FieldType.NUMBER, FieldType.SLIDER) and value is not None:
            err = self._validate_numeric(value)
            if err:
                return err

        if self.type == FieldType.SELECT and self.options:
            if value is not None and value not in self.options:
                return f"{self.label} must be one of: {', '.join(self.options)}"

        if self.type == FieldType.LIST and value is not None:
            err = self._validate_list(value)
            if err:
                return err

        if self.validation and value is not None:
            return self._validate_custom(value)

        return None

    def _validate_numeric(self, value: Any) -> Optional[str]:
        """Validate a numeric (NUMBER/SLIDER) field value."""
        try:
            num_value = float(value)
            if self.min_value is not None and num_value < self.min_value:
                return f"{self.label} must be at least {self.min_value}"
            if self.max_value is not None and num_value > self.max_value:
                return f"{self.label} must be at most {self.max_value}"
        except (TypeError, ValueError):
            return f"{self.label} must be a number"
        return None

    def _validate_list(self, value: Any) -> Optional[str]:
        """Validate a LIST field value (item count, types, and allowed options)."""
        items = value if isinstance(value, list) else []
        if self.min_items is not None and len(items) < self.min_items:
            return f"{self.label} requires at least {self.min_items} item(s)"
        if self.max_items is not None and len(items) > self.max_items:
            return f"{self.label} allows at most {self.max_items} item(s)"
        # Validate item types if specified
        if self.list_item_type == "number":
            for i, item in enumerate(items):
                try:
                    float(item)
                except (TypeError, ValueError):
                    return f"{self.label} item {i + 1} must be a number"
        # Validate against options if not allowing custom values
        if not self.allow_custom and self.options:
            for item in items:
                if item not in self.options:
                    return f"{self.label} item '{item}' not in allowed options"
        return None

    def _validate_custom(self, value: Any) -> Optional[str]:
        """Run custom validation callable."""
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


class SecretValue:
    """Wrapper preventing accidental secret exposure in logs/repr.

    Secrets loaded into memory are wrapped in this class to prevent
    accidental exposure via logging, print statements, or crash dumps.
    The actual value is only accessible via get_secret_value().

    Example:
        secret = SecretValue("my-api-key")
        print(secret)           # Output: ***
        print(repr(secret))     # Output: SecretValue('***')
        actual = secret.get_secret_value()  # Returns "my-api-key"
    """

    __slots__ = ("_value",)

    def __init__(self, value: str):
        """Initialize with a secret value.

        Args:
            value: The secret string to wrap.
        """
        self._value = value

    def __repr__(self) -> str:
        """Return masked representation."""
        return "SecretValue('***')"

    def __str__(self) -> str:
        """Return masked string."""
        return "***"

    def __eq__(self, other: object) -> bool:
        """Compare secret values."""
        if isinstance(other, SecretValue):
            return self._value == other._value
        return False

    def __hash__(self) -> int:
        """Hash based on value for use in sets/dicts."""
        return hash(self._value)

    def __bool__(self) -> bool:
        """Return True if value is non-empty."""
        return bool(self._value)

    def get_secret_value(self) -> str:
        """Get the actual secret value.

        Returns:
            The unwrapped secret string.
        """
        return self._value


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
