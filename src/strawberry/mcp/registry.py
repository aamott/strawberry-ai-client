"""Registry for managing multiple MCP server connections."""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from strawberry.mcp.adapter import MCPSkillAdapter
from strawberry.mcp.client import MCPClient, MCPToolResult
from strawberry.mcp.config import MCPServerConfig
from strawberry.skills.loader import SkillInfo

logger = logging.getLogger(__name__)


class MCPRegistry:
    """Manages multiple MCP server connections.

    Provides a unified interface for:
    - Starting/stopping all configured MCP servers
    - Listing tools across all servers as SkillInfo objects
    - Routing tool calls to the appropriate server

    Example:
        configs = [
            MCPServerConfig(name="filesystem", command="npx", args=[...]),
            MCPServerConfig(name="brave-search", command="npx", args=[...]),
        ]
        registry = MCPRegistry(configs)
        await registry.start_all()

        # Get as skills for unified discovery
        skills = registry.get_all_skills()

        # Call a tool
        result = await registry.call_tool("FilesystemMCP", "read_file", path="/tmp/x")
    """

    def __init__(self, configs: Optional[List[MCPServerConfig]] = None):
        """Initialize MCP registry.

        Args:
            configs: List of server configurations.
        """
        self._configs: Dict[str, MCPServerConfig] = {}
        self._clients: Dict[str, MCPClient] = {}
        self._skills: Dict[str, SkillInfo] = {}  # skill_name -> SkillInfo
        self._skill_to_server: Dict[str, str] = {}  # skill_name -> server_name
        self._adapter = MCPSkillAdapter()

        if configs:
            for config in configs:
                self.add_server(config)

    def add_server(self, config: MCPServerConfig) -> None:
        """Add a server configuration.

        Args:
            config: Server configuration to add.
        """
        if config.name in self._configs:
            logger.warning(f"MCP server '{config.name}' already configured, replacing")

        self._configs[config.name] = config
        logger.info(f"Added MCP server config: {config.name}")

    def remove_server(self, server_name: str) -> None:
        """Remove a server configuration.

        Args:
            server_name: Name of the server to remove.
        """
        if server_name in self._configs:
            del self._configs[server_name]
        if server_name in self._clients:
            # Note: caller should stop the client first
            del self._clients[server_name]

        # Remove associated skill
        fallback_config = MCPServerConfig(name=server_name, command="")
        skill_name = self._configs.get(server_name, fallback_config).skill_name
        if skill_name in self._skills:
            del self._skills[skill_name]
        if skill_name in self._skill_to_server:
            del self._skill_to_server[skill_name]

    async def start_all(self) -> Dict[str, bool]:
        """Start all enabled MCP servers.

        Returns:
            Dictionary mapping server names to success status.
        """
        results = {}

        for name, config in self._configs.items():
            if not config.enabled:
                logger.info(f"MCP server '{name}' is disabled, skipping")
                results[name] = False
                continue

            try:
                client = MCPClient(config)
                await client.start()
                self._clients[name] = client

                # Convert tools to SkillInfo
                skill_info = self._adapter.as_skill_info(name, client.tools)
                self._skills[skill_info.name] = skill_info
                self._skill_to_server[skill_info.name] = name

                results[name] = True
                logger.info(
                    f"Started MCP server '{name}' as '{skill_info.name}' "
                    f"with {len(client.tools)} tools"
                )

            except Exception as e:
                logger.error(f"Failed to start MCP server '{name}': {e}")
                results[name] = False

        return results

    async def stop_all(self) -> None:
        """Stop all running MCP servers."""
        for name, client in list(self._clients.items()):
            try:
                await client.stop()
                logger.info(f"Stopped MCP server '{name}'")
            except Exception as e:
                logger.error(f"Error stopping MCP server '{name}': {e}")

        self._clients.clear()
        self._skills.clear()
        self._skill_to_server.clear()

    async def start_server(self, server_name: str) -> bool:
        """Start a specific MCP server.

        Args:
            server_name: Name of the server to start.

        Returns:
            True if successful.
        """
        if server_name not in self._configs:
            logger.error(f"MCP server '{server_name}' not configured")
            return False

        config = self._configs[server_name]

        try:
            client = MCPClient(config)
            await client.start()
            self._clients[server_name] = client

            skill_info = self._adapter.as_skill_info(server_name, client.tools)
            self._skills[skill_info.name] = skill_info
            self._skill_to_server[skill_info.name] = server_name

            return True
        except Exception as e:
            logger.error(f"Failed to start MCP server '{server_name}': {e}")
            return False

    async def stop_server(self, server_name: str) -> None:
        """Stop a specific MCP server.

        Args:
            server_name: Name of the server to stop.
        """
        if server_name in self._clients:
            await self._clients[server_name].stop()
            del self._clients[server_name]

            # Find and remove skill
            skill_name = None
            for sn, srv in self._skill_to_server.items():
                if srv == server_name:
                    skill_name = sn
                    break

            if skill_name:
                del self._skills[skill_name]
                del self._skill_to_server[skill_name]

    async def restart_server(self, server_name: str) -> bool:
        """Restart a specific MCP server.

        Args:
            server_name: Name of the server to restart.

        Returns:
            True if successful.
        """
        await self.stop_server(server_name)
        return await self.start_server(server_name)

    def get_all_skills(self) -> List[SkillInfo]:
        """Get all MCP servers as SkillInfo objects.

        Returns:
            List of SkillInfo objects for connected servers.
        """
        return list(self._skills.values())

    def get_skill(self, skill_name: str) -> Optional[SkillInfo]:
        """Get a specific skill by name.

        Args:
            skill_name: Skill name (e.g., "BraveSearchMCP").

        Returns:
            SkillInfo or None if not found.
        """
        return self._skills.get(skill_name)

    def has_skill(self, skill_name: str) -> bool:
        """Check if a skill exists.

        Args:
            skill_name: Skill name to check.

        Returns:
            True if the skill exists.
        """
        return skill_name in self._skills

    def get_server_for_skill(self, skill_name: str) -> Optional[str]:
        """Get the server name for a skill.

        Args:
            skill_name: Skill name (e.g., "BraveSearchMCP").

        Returns:
            Server name or None if not found.
        """
        return self._skill_to_server.get(skill_name)

    async def call_tool(
        self,
        skill_name: str,
        tool_name: str,
        **kwargs: Any,
    ) -> MCPToolResult:
        """Call a tool on an MCP server.

        Args:
            skill_name: Skill name (e.g., "BraveSearchMCP").
            tool_name: Tool name (e.g., "search").
            **kwargs: Tool arguments.

        Returns:
            MCPToolResult with the result or error.

        Raises:
            ValueError: If skill or server not found.
        """
        server_name = self._skill_to_server.get(skill_name)
        if not server_name:
            raise ValueError(f"MCP skill not found: {skill_name}")

        client = self._clients.get(server_name)
        if not client:
            raise ValueError(f"MCP server not connected: {server_name}")

        return await client.call_tool(tool_name, kwargs)

    def call_method(
        self,
        skill_name: str,
        method_name: str,
        **kwargs: Any,
    ) -> Any:
        """Synchronous wrapper for call_tool (for compatibility with SkillLoader).

        Args:
            skill_name: Skill name.
            method_name: Method/tool name.
            **kwargs: Tool arguments.

        Returns:
            Tool result content or raises exception.

        Raises:
            ValueError: If skill not found.
            RuntimeError: If tool call fails.
        """
        # Run in event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # We're in an async context, create a task
            # This is tricky - we need to use run_coroutine_threadsafe or similar
            # For now, we'll raise and let the caller use async
            raise RuntimeError(
                "call_method cannot be used in async context. Use call_tool instead."
            )
        else:
            # Not in async context, run synchronously
            result = asyncio.run(self.call_tool(skill_name, method_name, **kwargs))

        if not result.success:
            raise RuntimeError(f"MCP tool call failed: {result.error}")

        return result.content

    async def call_method_async(
        self,
        skill_name: str,
        method_name: str,
        **kwargs: Any,
    ) -> Any:
        """Async version of call_method for use in async contexts.

        Args:
            skill_name: Skill name.
            method_name: Method/tool name.
            **kwargs: Tool arguments.

        Returns:
            Tool result content or raises exception.
        """
        result = await self.call_tool(skill_name, method_name, **kwargs)

        if not result.success:
            raise RuntimeError(f"MCP tool call failed: {result.error}")

        return result.content

    def get_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all configured servers.

        Returns:
            Dictionary mapping server names to status info.
        """
        status = {}
        for name, config in self._configs.items():
            client = self._clients.get(name)
            status[name] = {
                "configured": True,
                "enabled": config.enabled,
                "connected": client.connected if client else False,
                "tool_count": len(client.tools) if client else 0,
                "skill_name": config.skill_name,
            }
        return status

    @property
    def connected_servers(self) -> List[str]:
        """Get list of connected server names."""
        return [name for name, client in self._clients.items() if client.connected]

    @property
    def server_count(self) -> int:
        """Get number of configured servers."""
        return len(self._configs)

    @property
    def connected_count(self) -> int:
        """Get number of connected servers."""
        return len(self.connected_servers)
