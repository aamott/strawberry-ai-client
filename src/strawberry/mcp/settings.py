"""Settings loader for MCP configuration."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from strawberry.mcp.config import MCPServerConfig

logger = logging.getLogger(__name__)


def load_mcp_configs_from_settings(
    settings_path: Optional[Path] = None,
) -> List[MCPServerConfig]:
    """Load MCP server configurations from settings.yaml.

    Args:
        settings_path: Path to settings.yaml. If None, uses default location.

    Returns:
        List of MCPServerConfig objects.

    The settings.yaml should have an 'mcp' section like:
        mcp:
          enabled: true
          servers:
            - name: brave-search
              command: npx
              args: ["-y", "@anthropic/mcp-brave-search"]
              env:
                BRAVE_API_KEY: "${BRAVE_API_KEY}"
              enabled: true

    Alternatively, servers can be a JSON string for simpler UI editing.
    """
    if settings_path is None:
        # Default to config/settings.yaml relative to spoke root
        spoke_root = Path(__file__).parent.parent.parent.parent.parent
        settings_path = spoke_root / "config" / "settings.yaml"

    if not settings_path.exists():
        logger.debug(f"Settings file not found: {settings_path}")
        return []

    try:
        with open(settings_path) as f:
            settings = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"Failed to load settings: {e}")
        return []

    return parse_mcp_settings(settings)


def parse_mcp_settings(settings: Dict[str, Any]) -> List[MCPServerConfig]:
    """Parse MCP settings from a settings dictionary.

    Args:
        settings: Full settings dictionary.

    Returns:
        List of MCPServerConfig objects.
    """
    mcp_settings = settings.get("mcp", {})

    # Check if MCP is enabled
    if not mcp_settings.get("enabled", True):
        logger.info("MCP is disabled in settings")
        return []

    servers_data = mcp_settings.get("servers", [])

    # Handle JSON string format (from UI multiline input)
    if isinstance(servers_data, str):
        try:
            servers_data = json.loads(servers_data) if servers_data.strip() else []
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse MCP servers JSON: {e}")
            return []

    if not isinstance(servers_data, list):
        logger.error(f"MCP servers must be a list, got: {type(servers_data)}")
        return []

    configs = []
    for server_data in servers_data:
        if not isinstance(server_data, dict):
            logger.warning(f"Invalid server config (not a dict): {server_data}")
            continue

        try:
            config = MCPServerConfig.from_dict(server_data)
            configs.append(config)
            logger.debug(f"Loaded MCP server config: {config.name}")
        except Exception as e:
            logger.error(f"Failed to parse MCP server config: {e}")
            continue

    logger.info(f"Loaded {len(configs)} MCP server configurations")
    return configs


def save_mcp_configs_to_settings(
    configs: List[MCPServerConfig],
    settings_path: Optional[Path] = None,
    enabled: bool = True,
) -> bool:
    """Save MCP server configurations to settings.yaml.

    Args:
        configs: List of MCPServerConfig objects to save.
        settings_path: Path to settings.yaml.
        enabled: Whether MCP is enabled overall.

    Returns:
        True if successful.
    """
    if settings_path is None:
        spoke_root = Path(__file__).parent.parent.parent.parent.parent
        settings_path = spoke_root / "config" / "settings.yaml"

    # Load existing settings
    if settings_path.exists():
        try:
            with open(settings_path) as f:
                settings = yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load existing settings: {e}")
            settings = {}
    else:
        settings = {}
        settings_path.parent.mkdir(parents=True, exist_ok=True)

    # Update MCP section
    settings["mcp"] = {
        "enabled": enabled,
        "servers": [config.to_dict() for config in configs],
    }

    # Write back
    try:
        with open(settings_path, "w") as f:
            yaml.dump(settings, f, default_flow_style=False, sort_keys=False)
        logger.info(f"Saved {len(configs)} MCP server configs to {settings_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to save settings: {e}")
        return False
