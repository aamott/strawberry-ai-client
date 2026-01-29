"""MCP configuration loading.

This module handles loading MCP server configurations from the config file.
Currently uses config/mcp.json, but designed to integrate with the
SettingsManager once it supports dynamic lists.

Configuration file format (config/mcp.json):
{
  "mcpServers": {
    "server_name": {
      "command": "npx",
      "args": ["-y", "@some/mcp-server"],
      "env": {"API_KEY": "${API_KEY}"},
      "enabled": true
    }
  }
}
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import MCPServerConfig

logger = logging.getLogger(__name__)

# Default config file location (relative to project root)
DEFAULT_MCP_CONFIG_FILENAME = "config/mcp.json"


def _resolve_config_path_from_settings(project_root: Path) -> Path:
    """Resolve the MCP config path based on the saved settings.

    The value is stored in the SettingsManager under namespace `mcp`, key
    `config_path`. If the SettingsManager is not initialized or the setting
    is missing, falls back to DEFAULT_MCP_CONFIG_FILENAME.

    Args:
        project_root: Project root directory.

    Returns:
        A resolved Path (absolute).
    """
    from ..shared.settings import get_settings_manager

    settings = get_settings_manager()
    config_path_str = None
    if settings is not None:
        config_path_str = settings.get("mcp", "config_path", None)

    if not config_path_str:
        config_path_str = DEFAULT_MCP_CONFIG_FILENAME

    config_path = Path(str(config_path_str))
    if not config_path.is_absolute():
        config_path = project_root / config_path

    return config_path


def _ensure_config_file_exists(config_path: Path) -> None:
    """Ensure the MCP config file exists, without overwriting existing files.

    If the file doesn't exist, creates its parent directory and writes an
    empty config structure.

    Args:
        config_path: Path to the MCP config file.
    """
    if config_path.exists():
        return

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"mcpServers": {}}
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Created MCP config file at {config_path}")
    except OSError as e:
        logger.error(f"Failed to create MCP config file at {config_path}: {e}")


def ensure_mcp_config_file_at_path(config_path: Path) -> None:
    """Ensure an MCP config file exists at the given path.

    This is intended for UI flows: when the user changes the MCP config path
    in Settings and clicks Save, we create the file immediately so the user
    can visually confirm the path is correct.

    The file is created only if it does not already exist.

    Args:
        config_path: Path where the MCP config file should exist.
    """
    _ensure_config_file_exists(Path(config_path))


def _get_config_path() -> Path:
    """Get the path to the MCP config file.

    Returns:
        Path to the configured MCP config file.
    """
    # Import here to avoid circular imports
    from ..utils.paths import get_project_root

    project_root = get_project_root()
    config_path = _resolve_config_path_from_settings(project_root)
    _ensure_config_file_exists(config_path)
    return config_path


def load_mcp_configs_from_settings() -> List[MCPServerConfig]:
    """Load MCP server configurations from the config file.

    Reads config/mcp.json and converts each server entry into an
    MCPServerConfig. Returns an empty list if the file doesn't exist
    or is invalid.

    Returns:
        List of MCPServerConfig objects for enabled servers.
    """
    config_path = _get_config_path()

    if not config_path.exists():
        logger.debug(f"MCP config file not found: {config_path}")
        return []

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in MCP config: {e}")
        return []
    except OSError as e:
        logger.error(f"Failed to read MCP config: {e}")
        return []

    return parse_mcp_config(data)


def parse_mcp_config(data: Dict[str, Any]) -> List[MCPServerConfig]:
    """Parse MCP configuration data into MCPServerConfig objects.

    Args:
        data: Parsed JSON data from the config file.

    Returns:
        List of MCPServerConfig objects.
    """
    configs: List[MCPServerConfig] = []

    # Get the mcpServers section
    servers = data.get("mcpServers", {})
    if not isinstance(servers, dict):
        logger.error("Invalid mcpServers format in config (expected object)")
        return []

    for name, server_data in servers.items():
        config = _parse_server_config(name, server_data)
        if config is not None:
            configs.append(config)

    if not configs and servers:
        logger.info(
            "No MCP server configurations were loaded. "
            "Check per-server flags (enabled/disabled) and required fields (command)."
        )

    logger.info(f"Loaded {len(configs)} MCP server configurations")
    return configs


def _parse_server_config(
    name: str, data: Dict[str, Any]
) -> Optional[MCPServerConfig]:
    """Parse a single server configuration.

    Args:
        name: The server name (key in mcpServers).
        data: The server configuration object.

    Returns:
        MCPServerConfig if valid, None otherwise.
    """
    if not isinstance(data, dict):
        logger.warning(f"Invalid config for MCP server '{name}' (expected object)")
        return None

    # Command is required
    command = data.get("command")
    if not command or not isinstance(command, str):
        logger.warning(f"MCP server '{name}' missing required 'command' field")
        return None

    # Args is optional (default to empty list)
    args = data.get("args", [])
    if not isinstance(args, list):
        logger.warning(f"MCP server '{name}' has invalid 'args' (expected array)")
        args = []

    # Env is optional (default to empty dict)
    env = data.get("env", {})
    if not isinstance(env, dict):
        logger.warning(f"MCP server '{name}' has invalid 'env' (expected object)")
        env = {}

    # Enabled/disabled flags
    #
    # Many MCP configs use `disabled: true` (e.g., Claude Desktop style). Our
    # internal representation uses `enabled: bool`.
    enabled_value = data.get("enabled", None)
    disabled_value = data.get("disabled", None)

    enabled: bool
    if isinstance(enabled_value, bool):
        enabled = enabled_value
    elif isinstance(disabled_value, bool):
        enabled = not disabled_value
    else:
        enabled = True

    return MCPServerConfig(
        name=name,
        command=command,
        args=args,
        env=env,
        enabled=enabled,
    )


def save_mcp_configs(configs: List[MCPServerConfig]) -> bool:
    """Save MCP server configurations to the config file.

    This creates or overwrites the configured MCP config file with the provided
    configs.

    Args:
        configs: List of MCPServerConfig objects to save.

    Returns:
        True if save succeeded, False otherwise.
    """
    config_path = _get_config_path()

    # Build the config structure
    servers: Dict[str, Any] = {}
    for config in configs:
        servers[config.name] = {
            "command": config.command,
            "args": config.args,
            "env": config.env,
            "enabled": config.enabled,
        }

    data = {"mcpServers": servers}

    try:
        # Ensure directory exists
        config_path.parent.mkdir(parents=True, exist_ok=True)

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        logger.info(f"Saved {len(configs)} MCP server configs to {config_path}")
        return True

    except OSError as e:
        logger.error(f"Failed to save MCP config: {e}")
        return False
