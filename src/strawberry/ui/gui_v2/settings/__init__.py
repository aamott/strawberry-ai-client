"""GUI V2 Settings UI - themed field widgets.

Self-contained settings widgets that integrate with the gui_v2 theme system.
Uses SettingsManager schema to auto-render settings forms.

The SettingsWindow lives in gui_v2/components/settings_window.py and uses
these field widgets internally.
"""

from .field_base import BaseFieldWidget
from .field_factory import create_field_widget

__all__ = [
    "BaseFieldWidget",
    "create_field_widget",
]
