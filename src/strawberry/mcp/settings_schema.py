"""Settings schema definitions for MCP integration.

This module defines the MCP_SETTINGS_SCHEMA for MCP server settings.
Currently a placeholder - MCP configs are stored in config/mcp.json.

When the SettingsManager is upgraded to support dynamic lists, MCP server
configurations will be moved here.
"""

from typing import List

from strawberry.shared.settings import FieldType, SettingField

# MCP settings schema
# For now, MCP uses a separate config file (config/mcp.json).
# This schema provides a placeholder with info about where to configure MCP.
MCP_SETTINGS_SCHEMA: List[SettingField] = [
    SettingField(
        key="enabled",
        label="Enable MCP",
        type=FieldType.CHECKBOX,
        default=True,
        description="Enable MCP (Model Context Protocol) server integration",
        group="general",
    ),
    SettingField(
        key="config_path",
        label="Config File",
        type=FieldType.TEXT,
        default="config/mcp.json",
        description="Path to MCP server configuration file (relative to project root)",
        metadata={
            "help_text": (
                "For now, MCP servers are configured in a JSON file here.\n"
                "Example format:\n"
                "{\n"
                '  "mcpServers": {\n'
                '    "filesystem": {\n'
                '      "command": "npx",\n'
                '      "args": ["-y", "@modelcontextprotocol/server-filesystem",\n'
                '               "/path/to/files"]\n'
                "    }\n"
                "  }\n"
                "}"
            )
        },
        group="general",
    ),
]
