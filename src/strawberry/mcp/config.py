"""MCP server configuration.

This module defines the configuration dataclass for MCP servers.
Configuration can come from config/mcp.json or (future) the settings manager.
"""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server.

    Each MCP server runs as a subprocess and communicates via stdio.
    This config defines how to start and identify the server.

    Attributes:
        name: Unique identifier for this server (e.g., "home_assistant").
              Used to generate the skill class name: "HomeAssistantMCP".
        command: The executable to run (e.g., "npx", "python", "node").
        args: Command-line arguments for the executable.
        env: Environment variables to pass to the subprocess.
             Supports ${VAR} syntax for referencing os.environ.
        enabled: Whether this server should be started. Allows disabling
                 without removing the config.

    Example:
        >>> config = MCPServerConfig(
        ...     name="home_assistant",
        ...     command="npx",
        ...     args=["-y", "@home-assistant/mcp-server"],
        ...     env={"HASS_TOKEN": "${HASS_TOKEN}"},
        ... )
    """

    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True

    def get_skill_class_name(self) -> str:
        """Generate the skill class name from the server name.

        Converts snake_case server name to PascalCase with MCP suffix.
        Example: "home_assistant" -> "HomeAssistantMCP"

        Returns:
            The skill class name for this MCP server.
        """
        # Split by underscores and capitalize each part
        parts = self.name.split("_")
        pascal_name = "".join(part.capitalize() for part in parts)
        return f"{pascal_name}MCP"
