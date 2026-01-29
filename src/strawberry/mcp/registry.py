"""MCP server registry.

This module manages multiple MCP server connections. It provides:
- Batch start/stop of all configured servers
- Client lookup by name
- Aggregated skill list from all servers
- Tool call routing to the correct server
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from ..skills.loader import SkillInfo
from .adapter import MCPSkillAdapter
from .client import MCPClient
from .config import MCPServerConfig

logger = logging.getLogger(__name__)


class MCPRegistry:
    """Manages multiple MCP server connections.

    The registry is the main entry point for MCP integration. It:
    1. Holds configurations for all MCP servers
    2. Starts/stops server connections
    3. Provides unified access to all MCP skills
    4. Routes tool calls to the correct server

    Example:
        >>> configs = [MCPServerConfig(name="home_assistant", ...)]
        >>> registry = MCPRegistry(configs)
        >>> results = await registry.start_all()  # {"home_assistant": True}
        >>> skills = registry.get_all_skills()  # [SkillInfo(name="HomeAssistantMCP")]
        >>> result = await registry.call_tool("home_assistant", "turn_on_light", {...})
        >>> await registry.stop_all()
    """

    def __init__(self, configs: List[MCPServerConfig]) -> None:
        """Initialize the registry with server configurations.

        Only enabled configs are used. Disabled configs are ignored.

        Args:
            configs: List of MCP server configurations.
        """
        # Filter to only enabled configs
        self._configs = [c for c in configs if c.enabled]
        self._clients: Dict[str, MCPClient] = {}
        self._adapter = MCPSkillAdapter()

        # Cache of adapted skills (populated after start)
        self._skills_cache: Optional[List[SkillInfo]] = None

        logger.info(f"MCPRegistry initialized with {len(self._configs)} servers")

    @property
    def server_names(self) -> List[str]:
        """Get list of configured server names."""
        return [c.name for c in self._configs]

    async def start_all(self) -> Dict[str, bool]:
        """Start all configured MCP servers.

        Servers are started concurrently for efficiency. Each server's
        success/failure is tracked independently.

        Returns:
            Dict mapping server name to success status.
        """
        if not self._configs:
            logger.info("No MCP servers configured")
            return {}

        # Create clients for each config
        for config in self._configs:
            self._clients[config.name] = MCPClient(config)

        # Start all servers concurrently
        async def start_one(name: str) -> tuple[str, bool]:
            """Start a single server and return (name, success)."""
            client = self._clients[name]
            success = await client.start()
            return (name, success)

        tasks = [start_one(name) for name in self._clients]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        status: Dict[str, bool] = {}
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Unexpected error starting MCP server: {result}")
            else:
                name, success = result
                status[name] = success

        # Invalidate skills cache so it's regenerated
        self._skills_cache = None

        started = sum(1 for s in status.values() if s)
        logger.info(f"Started {started}/{len(status)} MCP servers")

        return status

    async def stop_all(self) -> None:
        """Stop all running MCP servers.

        Servers are stopped concurrently. Errors are logged but don't
        prevent other servers from stopping.
        """
        if not self._clients:
            return

        async def stop_one(client: MCPClient) -> None:
            """Stop a single server."""
            try:
                await client.stop()
            except Exception as e:
                logger.error(f"Error stopping MCP server '{client.name}': {e}")

        tasks = [stop_one(client) for client in self._clients.values()]
        await asyncio.gather(*tasks)

        self._clients.clear()
        self._skills_cache = None

        logger.info("Stopped all MCP servers")

    def get_client(self, name: str) -> Optional[MCPClient]:
        """Get a specific MCP client by server name.

        Args:
            name: The server name (e.g., "home_assistant").

        Returns:
            The MCPClient, or None if not found or not started.
        """
        return self._clients.get(name)

    def get_client_by_skill_name(self, skill_name: str) -> Optional[MCPClient]:
        """Get an MCP client by its skill class name.

        Args:
            skill_name: The skill class name (e.g., "HomeAssistantMCP").

        Returns:
            The MCPClient, or None if not found.
        """
        for client in self._clients.values():
            if client.skill_class_name == skill_name:
                return client
        return None

    def get_all_skills(self) -> List[SkillInfo]:
        """Get all MCP servers as SkillInfo objects.

        This is the main integration point with the skill system. Each
        connected MCP server is converted to a SkillInfo with methods
        for each tool.

        Returns:
            List of SkillInfo objects, one per connected MCP server.
        """
        # Return cached skills if available
        if self._skills_cache is not None:
            return self._skills_cache

        skills: List[SkillInfo] = []
        for client in self._clients.values():
            if client.is_started:
                skill_info = self._adapter.adapt_server(client)
                skills.append(skill_info)

        self._skills_cache = skills
        return skills

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Execute a tool on a specific MCP server.

        Args:
            server_name: The server name (e.g., "home_assistant").
            tool_name: The tool name (e.g., "turn_on_light").
            arguments: Tool arguments.

        Returns:
            The tool's result.

        Raises:
            ValueError: If the server is not found or not started.
        """
        client = self._clients.get(server_name)
        if client is None:
            raise ValueError(f"MCP server '{server_name}' not found")

        if not client.is_started:
            raise ValueError(f"MCP server '{server_name}' is not started")

        return await client.call_tool(tool_name, arguments)

    async def call_tool_by_skill(
        self, skill_name: str, method_name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Execute a tool using skill class name and method name.

        This is the interface used by the Gatekeeper when routing calls
        from LLM-generated code like: device.HomeAssistantMCP.turn_on_light()

        Args:
            skill_name: The skill class name (e.g., "HomeAssistantMCP").
            method_name: The method/tool name (e.g., "turn_on_light").
            arguments: Tool arguments.

        Returns:
            The tool's result.

        Raises:
            ValueError: If the skill/server is not found.
        """
        client = self.get_client_by_skill_name(skill_name)
        if client is None:
            raise ValueError(f"MCP skill '{skill_name}' not found")

        return await client.call_tool(method_name, arguments)

    def is_mcp_skill(self, skill_name: str) -> bool:
        """Check if a skill name refers to an MCP server.

        Args:
            skill_name: The skill class name.

        Returns:
            True if this is an MCP skill.
        """
        return self.get_client_by_skill_name(skill_name) is not None
