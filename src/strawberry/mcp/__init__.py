"""MCP (Model Context Protocol) integration for Strawberry.

This module provides integration with MCP servers, allowing them to be
used alongside Python skills with the same calling convention:
    device.<ServerName>MCP.<tool_name>(<params>)

Key components:
- MCPServerConfig: Configuration dataclass for MCP servers
- MCPClient: Wrapper around MCP SDK for a single server connection
- MCPRegistry: Manages multiple MCP server connections
- MCPSkillAdapter: Converts MCP tools to SkillInfo format
"""

from strawberry.mcp.adapter import MCPSkillAdapter
from strawberry.mcp.client import MCPClient
from strawberry.mcp.config import MCPServerConfig
from strawberry.mcp.registry import MCPRegistry

__all__ = [
    "MCPServerConfig",
    "MCPClient",
    "MCPRegistry",
    "MCPSkillAdapter",
]
