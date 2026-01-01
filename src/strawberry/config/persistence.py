"""Persistence helpers for user-editable configuration.

We split configuration into:
- config/config.yaml: non-secret settings
- .env: secrets (tokens / API keys)

This module coordinates writing updates and applying them immediately to the
running process.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from .env_file import update_env_file
from .yaml_file import YamlUpdate, apply_yaml_updates_preserve_comments


DEFAULT_CONFIG_PATH = Path("config/config.yaml")
DEFAULT_ENV_PATH = Path(".env")


@dataclass(frozen=True)
class PersistenceResult:
    wrote_config: bool
    wrote_env: bool


def reload_env(env_path: Path = DEFAULT_ENV_PATH) -> None:
    """Reload .env into the current process environment."""
    if env_path.exists():
        load_dotenv(env_path, override=True)


def apply_env_updates_to_process(updates: Dict[str, Optional[str]]) -> None:
    """Apply env updates to os.environ immediately."""
    for key, val in updates.items():
        if val is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = val


def persist_settings_and_env(
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    env_path: Path = DEFAULT_ENV_PATH,
    yaml_updates: Dict[str, Any],
    env_updates: Dict[str, Optional[str]],
) -> PersistenceResult:
    """Persist YAML + .env updates and apply env changes immediately."""
    wrote_config = False
    wrote_env = False

    # Write YAML
    if yaml_updates:
        updates = []
        for dotted, value in yaml_updates.items():
            path = tuple(part for part in dotted.split(".") if part)
            updates.append(YamlUpdate(path=path, value=value))

        apply_yaml_updates_preserve_comments(config_path, updates)
        wrote_config = True

    # Write .env
    if env_updates:
        update_env_file(env_path, env_updates)
        wrote_env = True

        # Apply immediately
        apply_env_updates_to_process(env_updates)
        reload_env(env_path)

    return PersistenceResult(wrote_config=wrote_config, wrote_env=wrote_env)
