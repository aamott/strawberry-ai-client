"""Theme loader — discovers and loads themes from YAML files.

Themes are stored as YAML files in a configurable themes directory
(default: config/themes/). Each file defines a color palette that maps
to the Theme dataclass fields.

Built-in themes are shipped as YAML files and are auto-created in the
themes directory if they don't already exist.
"""

import logging
import shutil
from pathlib import Path
from typing import Dict, Optional

import yaml

from .base import Theme

logger = logging.getLogger(__name__)

# Directory containing built-in theme YAML files shipped with the package
_BUILTIN_DIR = Path(__file__).parent / "builtin"


def load_theme_from_yaml(path: Path) -> Optional[Theme]:
    """Load a single theme from a YAML file.

    Args:
        path: Path to the YAML file.

    Returns:
        A Theme instance, or None if the file is invalid.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            logger.warning("Theme file %s is not a valid YAML dict", path)
            return None

        # Ensure 'name' is present (fall back to filename stem)
        if "name" not in data:
            data["name"] = path.stem

        # Let the dataclass constructor validate required fields
        return Theme(**data)

    except TypeError as e:
        logger.warning("Theme file %s has missing/extra fields: %s", path, e)
        return None
    except yaml.YAMLError as e:
        logger.warning("Theme file %s has invalid YAML: %s", path, e)
        return None
    except Exception:
        logger.exception("Failed to load theme from %s", path)
        return None


def discover_themes(themes_dir: Path) -> Dict[str, Theme]:
    """Scan a directory for theme YAML files and load them.

    Files starting with '_' (e.g. _template.yaml) are skipped.

    Args:
        themes_dir: Directory to scan.

    Returns:
        Dict mapping theme name to Theme instance.
    """
    themes: Dict[str, Theme] = {}

    if not themes_dir.is_dir():
        logger.warning("Themes directory does not exist: %s", themes_dir)
        return themes

    for path in sorted(themes_dir.glob("*.yaml")):
        # Skip template and hidden files
        if path.name.startswith("_") or path.name.startswith("."):
            continue

        theme = load_theme_from_yaml(path)
        if theme:
            themes[theme.name] = theme
            logger.debug("Loaded theme '%s' from %s", theme.name, path.name)

    return themes


def ensure_builtin_themes(themes_dir: Path) -> None:
    """Copy built-in theme files to the themes directory if they don't exist.

    This ensures users always have the default themes available, even on
    first run. Existing files are never overwritten.

    Args:
        themes_dir: Target themes directory.
    """
    themes_dir.mkdir(parents=True, exist_ok=True)

    if not _BUILTIN_DIR.is_dir():
        logger.warning("Built-in themes directory not found: %s", _BUILTIN_DIR)
        return

    for src in _BUILTIN_DIR.glob("*.yaml"):
        dest = themes_dir / src.name
        if not dest.exists():
            shutil.copy2(src, dest)
            logger.info("Installed built-in theme: %s", src.name)


def get_theme_names(themes_dir: Path) -> list[str]:
    """Get a sorted list of available theme names (without loading full themes).

    Args:
        themes_dir: Directory to scan.

    Returns:
        Sorted list of theme names (filename stems, excluding _template).
    """
    if not themes_dir.is_dir():
        return []

    names = []
    for path in sorted(themes_dir.glob("*.yaml")):
        if path.name.startswith("_") or path.name.startswith("."):
            continue
        names.append(path.stem)
    return names
