"""MCP client wrapper.

This module provides a thin wrapper around the MCP Python SDK for managing
a single MCP server connection. It handles:
- Starting/stopping the server subprocess
- MCP protocol handshake (initialize)
- Tool discovery and caching
- Tool execution

The client uses stdio transport (stdin/stdout) to communicate with the server.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, Tool

from .config import MCPServerConfig

logger = logging.getLogger(__name__)


def _expand_env_vars(value: str) -> str:
    """Expand ${VAR} references in a string using os.environ.

    Args:
        value: String that may contain ${VAR} placeholders.

    Returns:
        String with placeholders replaced by environment variable values.
        If a variable is not set, the placeholder is replaced with empty string.
    """
    # Pattern matches ${VAR_NAME}
    pattern = r"\$\{([^}]+)\}"

    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, "")

    return re.sub(pattern, replacer, value)


class MCPClient:
    """Wrapper for a single MCP server connection.

    This class manages the lifecycle of an MCP server subprocess and provides
    methods to interact with its tools. It uses the official MCP Python SDK.

    The client is async-first since MCP communication is inherently async.

    Attributes:
        config: The server configuration.
        tools: Cached list of tools from the server (populated after start).

    Example:
        >>> client = MCPClient(config)
        >>> await client.start()
        >>> tools = client.tools  # List of Tool objects
        >>> result = await client.call_tool("turn_on_light", {"entity_id": "light.kitchen"})
        >>> await client.stop()
    """

    def __init__(self, config: MCPServerConfig) -> None:
        """Initialize the MCP client.

        Args:
            config: Server configuration specifying command, args, and env.
        """
        self.config = config
        self.tools: List[Tool] = []

        # Internal state
        self._session: Optional[ClientSession] = None
        self._started = False

        # Context managers for cleanup
        self._stdio_cm: Optional[Any] = None
        self._session_cm: Optional[Any] = None
        self._read_stream: Optional[Any] = None
        self._write_stream: Optional[Any] = None

    @property
    def name(self) -> str:
        """Get the server name."""
        return self.config.name

    @property
    def skill_class_name(self) -> str:
        """Get the skill class name (e.g., HomeAssistantMCP)."""
        return self.config.get_skill_class_name()

    @property
    def is_started(self) -> bool:
        """Check if the server is started and connected."""
        return self._started and self._session is not None

    async def start(self) -> bool:
        """Start the MCP server and establish connection.

        This method:
        1. Starts the server subprocess with configured command/args/env
        2. Performs the MCP initialize handshake
        3. Fetches and caches available tools

        Returns:
            True if server started successfully, False otherwise.
        """
        if self._started:
            logger.warning(f"MCP server '{self.name}' already started")
            return True

        try:
            # Expand environment variables in the config
            env = {k: _expand_env_vars(v) for k, v in self.config.env.items()}

            # Create server parameters for stdio transport
            server_params = StdioServerParameters(
                command=self.config.command,
                args=self.config.args,
                env=env if env else None,
            )

            logger.info(f"Starting MCP server '{self.name}': {self.config.command}")

            # Start the stdio client (this spawns the subprocess)
            self._stdio_cm = stdio_client(server_params)
            self._read_stream, self._write_stream = await self._stdio_cm.__aenter__()

            # Create and initialize the MCP session
            self._session_cm = ClientSession(self._read_stream, self._write_stream)
            self._session = await self._session_cm.__aenter__()

            # Perform MCP handshake
            await self._session.initialize()

            # Fetch available tools
            tools_response = await self._session.list_tools()
            self.tools = tools_response.tools

            self._started = True
            logger.info(
                f"MCP server '{self.name}' started with {len(self.tools)} tools"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to start MCP server '{self.name}': {e}")
            # Clean up on failure
            await self._cleanup()
            return False

    async def stop(self) -> None:
        """Stop the MCP server and clean up resources.

        This gracefully closes the MCP session and terminates the subprocess.
        Safe to call multiple times.
        """
        if not self._started:
            return

        logger.info(f"Stopping MCP server '{self.name}'")
        await self._cleanup()
        self._started = False

    async def _cleanup(self) -> None:
        """Clean up session and stdio context managers."""
        # Close session first
        if self._session_cm is not None:
            try:
                await self._session_cm.__aexit__(None, None, None)
            except Exception as e:
                logger.debug(f"Error closing session for '{self.name}': {e}")
            self._session_cm = None
            self._session = None

        # Then close stdio (terminates subprocess)
        if self._stdio_cm is not None:
            try:
                await self._stdio_cm.__aexit__(None, None, None)
            except Exception as e:
                logger.debug(f"Error closing stdio for '{self.name}': {e}")
            self._stdio_cm = None
            self._read_stream = None
            self._write_stream = None

        self.tools = []

    async def call_tool(
        self, tool_name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Execute a tool on the MCP server.

        Args:
            tool_name: Name of the tool to call.
            arguments: Dictionary of arguments to pass to the tool.

        Returns:
            The tool's result. Format depends on the tool implementation.

        Raises:
            RuntimeError: If the server is not started.
            ValueError: If the tool is not found.
            Exception: If the tool execution fails.
        """
        if not self.is_started or self._session is None:
            raise RuntimeError(f"MCP server '{self.name}' is not started")

        # Validate tool exists
        tool_names = [t.name for t in self.tools]
        if tool_name not in tool_names:
            raise ValueError(
                f"Tool '{tool_name}' not found on server '{self.name}'. "
                f"Available: {tool_names}"
            )

        logger.debug(f"Calling MCP tool '{self.name}.{tool_name}' with {arguments}")

        try:
            result: CallToolResult = await self._session.call_tool(
                tool_name, arguments or {}
            )

            # Extract content from the result
            # MCP tools return a list of content blocks (text, image, etc.)
            return self._extract_result(result)

        except Exception as e:
            logger.error(f"MCP tool call failed: {self.name}.{tool_name}: {e}")
            raise

    def _extract_result(self, result: CallToolResult) -> Any:
        """Extract a usable result from CallToolResult.

        MCP tool results contain a list of content blocks. This method
        extracts the content in a format suitable for returning to the LLM.

        Args:
            result: The raw CallToolResult from the MCP SDK.

        Returns:
            Extracted content. If single text block, returns the string.
            If multiple blocks, returns a list of content items.
        """
        if not result.content:
            return None

        # If there's only one text content block, return just the text
        if len(result.content) == 1:
            block = result.content[0]
            if hasattr(block, "text"):
                return block.text
            elif hasattr(block, "data"):
                # Binary content (image, etc.)
                return {"type": "binary", "mimeType": getattr(block, "mimeType", None)}

        # Multiple content blocks - return structured data
        contents = []
        for block in result.content:
            if hasattr(block, "text"):
                contents.append({"type": "text", "text": block.text})
            elif hasattr(block, "data"):
                contents.append(
                    {"type": "binary", "mimeType": getattr(block, "mimeType", None)}
                )
        return contents

    def get_tool(self, name: str) -> Optional[Tool]:
        """Get a specific tool by name.

        Args:
            name: The tool name.

        Returns:
            The Tool object, or None if not found.
        """
        for tool in self.tools:
            if tool.name == name:
                return tool
        return None
