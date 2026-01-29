"""MCP (Model Context Protocol) integration for Strawberry.

This module provides integration with MCP servers, allowing them to be
used alongside Python skills with the same calling convention:
    device.<ServerName>MCP.<tool_name>(<params>)

Key components:
- MCPServerConfig: Configuration dataclass for MCP servers
- MCPClient: Wrapper around MCP SDK for a single server connection
- MCPRegistry: Manages multiple MCP server connections
- MCPSkillAdapter: Converts MCP tools to SkillInfo format

Usage:
    # Load configs from config/mcp.json
    configs = load_mcp_configs_from_settings()

    # Create registry and start servers
    registry = MCPRegistry(configs)
    await registry.start_all()

    # Get skills (for integration with SkillService)
    mcp_skills = registry.get_all_skills()

    # Call a tool
    result = await registry.call_tool("home_assistant", "turn_on_light", {...})

    # Stop all servers
    await registry.stop_all()
"""

from .adapter import MCPSkillAdapter, get_mcp_client_from_skill, is_mcp_skill
from .client import MCPClient
from .config import MCPServerConfig
from .registry import MCPRegistry
from .settings import load_mcp_configs_from_settings, parse_mcp_config, save_mcp_configs

__all__ = [
    # Config
    "MCPServerConfig",
    # Client
    "MCPClient",
    # Registry
    "MCPRegistry",
    # Adapter
    "MCPSkillAdapter",
    "is_mcp_skill",
    "get_mcp_client_from_skill",
    # Settings
    "load_mcp_configs_from_settings",
    "parse_mcp_config",
    "save_mcp_configs",
]
