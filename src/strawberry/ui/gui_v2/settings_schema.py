"""GUI appearance settings schema.

Registers a 'gui' namespace on the 'General' tab with theme selection,
font size, start-maximized toggle, and an action to open the themes folder.
"""

import logging
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ...shared.settings import FieldType, SettingField

if TYPE_CHECKING:
    from ...shared.settings import SettingsManager

logger = logging.getLogger(__name__)

# Default themes directory (relative to project root)
_DEFAULT_THEMES_DIR_NAME = "config/themes"


def _get_themes_dir(settings_manager: "SettingsManager") -> Path:
    """Resolve the themes directory path.

    Args:
        settings_manager: The settings manager (used to find config_dir).

    Returns:
        Absolute path to the themes directory.
    """
    # config_dir is typically <project_root>/config
    config_dir = getattr(settings_manager, "_config_dir", None)
    if config_dir:
        return Path(config_dir) / "themes"

    # Fallback: project root / config / themes
    from ...utils.paths import get_project_root

    return get_project_root() / _DEFAULT_THEMES_DIR_NAME


def get_gui_schema() -> list[SettingField]:
    """Get the GUI appearance settings schema.

    Returns:
        List of SettingField definitions.
    """
    return [
        SettingField(
            key="theme",
            label="Theme",
            type=FieldType.DYNAMIC_SELECT,
            default="dark",
            description="Color theme for the application. Drop .yaml files "
            "into the themes folder to add custom themes.",
            options_provider="gui_theme_names",
            group="appearance",
        ),
        SettingField(
            key="font_size",
            label="Font Size",
            type=FieldType.NUMBER,
            default=14,
            min_value=10,
            max_value=20,
            description="Base font size in pixels.",
            group="appearance",
        ),
        SettingField(
            key="start_maximized",
            label="Start Maximized",
            type=FieldType.CHECKBOX,
            default=False,
            description="Start the application window maximized.",
            group="window",
        ),
        SettingField(
            key="open_themes_folder",
            label="Open Themes Folder",
            type=FieldType.ACTION,
            action="open_themes_folder",
            description="Open the themes folder to add or edit custom themes. "
            "Copy _template.yaml to create a new theme.",
            group="appearance",
        ),
    ]


def register_gui_schema(settings_manager: "SettingsManager") -> None:
    """Register the GUI settings namespace and populate theme options.

    Args:
        settings_manager: The settings manager to register with.
    """
    from .themes.loader import ensure_builtin_themes, get_theme_names

    themes_dir = _get_themes_dir(settings_manager)

    # Ensure built-in themes exist on disk
    ensure_builtin_themes(themes_dir)

    # Register the schema
    settings_manager.register(
        namespace="gui",
        schema=get_gui_schema(),
        display_name="Appearance",
        tab="General",
        order=50,
    )

    # Register theme names as a dynamic options provider (callable)
    def _theme_names_provider() -> list[str]:
        names = get_theme_names(themes_dir)
        return names if names else ["dark", "light"]

    settings_manager.register_options_provider(
        "gui_theme_names", _theme_names_provider
    )

    # Register the action handler for opening the themes folder
    settings_manager.register_action_handler(
        "gui",
        "open_themes_folder",
        lambda: _open_themes_folder(themes_dir),
    )

    logger.debug(
        "Registered GUI settings (themes: %s)",
        ", ".join(_theme_names_provider()),
    )


def _open_themes_folder(themes_dir: Path) -> None:
    """Open the themes folder in the system file manager.

    Args:
        themes_dir: Path to the themes directory.
    """
    themes_dir.mkdir(parents=True, exist_ok=True)

    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", str(themes_dir)])  # noqa: S603, S607
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(themes_dir)])  # noqa: S603, S607
        else:
            # Linux / other — try xdg-open
            subprocess.Popen(["xdg-open", str(themes_dir)])  # noqa: S603, S607
        logger.info("Opened themes folder: %s", themes_dir)
    except Exception:
        logger.exception("Failed to open themes folder: %s", themes_dir)
