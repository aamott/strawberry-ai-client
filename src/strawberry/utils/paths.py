"""Path resolution utilities."""

from pathlib import Path


def get_project_root() -> Path:
    """Get the project root directory (ai-pc-spoke).

    Returns:
        Path to the project root.
    """
    # This file is in src/strawberry/utils/paths.py
    # .parents[0] -> utils
    # .parents[1] -> strawberry
    # .parents[2] -> src
    # .parents[3] -> ai-pc-spoke
    return Path(__file__).resolve().parents[3]


def get_skills_dir() -> Path:
    """Get the default skills directory.

    Returns:
        Path to the skills directory (project_root/skills).
    """
    return get_project_root() / "skills"
