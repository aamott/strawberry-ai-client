"""Settings UI widgets for Qt.

This package provides Qt widgets for displaying and editing settings
using the SettingsManager and SettingsViewModel.
"""

from .namespace_widget import NamespaceSettingsWidget
from .provider_widget import ProviderSettingsWidget
from .schema_field_widget import SchemaFieldWidget
from .settings_dialog import SettingsDialog

__all__ = [
    "SettingsDialog",
    "NamespaceSettingsWidget",
    "ProviderSettingsWidget",
    "SchemaFieldWidget",
]
