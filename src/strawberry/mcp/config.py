"""Configuration dataclasses for MCP servers."""

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server.

    Attributes:
        name: Unique identifier for the server (e.g., "brave-search").
        command: Command to run the server (e.g., "npx", "python").
        args: Arguments to pass to the command.
        env: Environment variables for the server process.
              Supports ${VAR} syntax to reference .env variables.
        enabled: Whether this server should be started.
        transport: Connection type - "stdio" for subprocess, "sse" for HTTP.
        url: URL for SSE transport (required if transport="sse").
        timeout: Timeout in seconds for tool calls (default 30).
        restart_on_failure: Whether to restart the server if it crashes.
    """

    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    transport: Literal["stdio", "sse"] = "stdio"
    url: Optional[str] = None
    timeout: float = 30.0
    restart_on_failure: bool = True

    def __post_init__(self) -> None:
        """Validate configuration."""
        if not self.name:
            raise ValueError("MCP server name is required")
        if not self.command and self.transport == "stdio":
            raise ValueError(f"MCP server '{self.name}': command is required for stdio transport")
        if self.transport == "sse" and not self.url:
            raise ValueError(f"MCP server '{self.name}': url is required for sse transport")

    def get_resolved_env(self) -> Dict[str, str]:
        """Resolve environment variables with ${VAR} syntax.

        Returns:
            Dictionary with resolved environment variable values.
        """
        resolved = {}
        pattern = re.compile(r"\$\{([^}]+)\}")

        for key, value in self.env.items():
            def replace_var(match: re.Match) -> str:
                var_name = match.group(1)
                return os.environ.get(var_name, "")

            resolved[key] = pattern.sub(replace_var, value)

        return resolved

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "command": self.command,
            "args": self.args,
            "env": self.env,
            "enabled": self.enabled,
            "transport": self.transport,
            "url": self.url,
            "timeout": self.timeout,
            "restart_on_failure": self.restart_on_failure,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPServerConfig":
        """Create from dictionary.

        Args:
            data: Dictionary with server configuration.

        Returns:
            MCPServerConfig instance.
        """
        return cls(
            name=data.get("name", ""),
            command=data.get("command", ""),
            args=data.get("args", []),
            env=data.get("env", {}),
            enabled=data.get("enabled", True),
            transport=data.get("transport", "stdio"),
            url=data.get("url"),
            timeout=data.get("timeout", 30.0),
            restart_on_failure=data.get("restart_on_failure", True),
        )

    @property
    def skill_name(self) -> str:
        """Get the skill name for this MCP server.

        Converts server name to PascalCase and appends 'MCP'.
        Example: "brave-search" -> "BraveSearchMCP"
        """
        # Split by hyphens and underscores
        parts = re.split(r"[-_]", self.name)
        # Capitalize each part and join
        pascal = "".join(part.capitalize() for part in parts)
        return f"{pascal}MCP"
