"""Settings management package.

This package provides a centralized settings service with namespace isolation,
allowing different modules to manage their own settings without conflicts.

Example usage:
    from strawberry.shared.settings import SettingsManager, SettingField, FieldType

    # Initialize at app startup
    settings = SettingsManager(config_dir=Path("config"))

    # Register a namespace with schema
    settings.register("my_module", "My Module", [
        SettingField("api_key", "API Key", FieldType.PASSWORD, secret=True),
        SettingField("enabled", "Enable Feature", FieldType.CHECKBOX, default=True),
    ])

    # Get/set values
    api_key = settings.get("my_module", "api_key")
    settings.set("my_module", "enabled", False)
"""

from .manager import (
    MigrationFunc,
    RegisteredNamespace,
    SettingsManager,
    get_settings_manager,
    init_settings_manager,
)
from .schema import (
    ActionResult,
    FieldType,
    SecretValue,
    SettingField,
    ValidationMode,
    get_field_by_key,
    group_fields,
)
from .storage import parse_list_value
from .view_model import (
    ProviderSection,
    SettingsSection,
    SettingsViewModel,
    ValidationResult,
)

__all__ = [
    # Schema types
    "FieldType",
    "SettingField",
    "ActionResult",
    "SecretValue",
    "ValidationMode",
    "get_field_by_key",
    "group_fields",
    # Manager
    "SettingsManager",
    "RegisteredNamespace",
    "MigrationFunc",
    "get_settings_manager",
    "init_settings_manager",
    # ViewModel
    "SettingsViewModel",
    "SettingsSection",
    "ProviderSection",
    "ValidationResult",
    # Storage utilities
    "parse_list_value",
]
