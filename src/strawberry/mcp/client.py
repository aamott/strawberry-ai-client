"""MCP client wrapper for a single server connection."""

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

from strawberry.mcp.config import MCPServerConfig

logger = logging.getLogger(__name__)


@dataclass
class MCPTool:
    """Representation of an MCP tool.

    Attributes:
        name: Tool name (e.g., "search", "read_file").
        description: Human-readable description of what the tool does.
        input_schema: JSON Schema describing the tool's parameters.
    """

    name: str
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPToolResult:
    """Result from an MCP tool call.

    Attributes:
        success: Whether the call succeeded.
        content: Result content (text, data, etc.).
        error: Error message if the call failed.
        is_error: Whether the result is an error from the tool itself.
    """

    success: bool
    content: Any = None
    error: Optional[str] = None
    is_error: bool = False


class MCPClient:
    """Wrapper around MCP SDK for a single server connection.

    Handles starting/stopping the server process and communicating via
    the MCP protocol (JSON-RPC over stdio or SSE).

    Example:
        config = MCPServerConfig(
            name="filesystem",
            command="npx",
            args=["-y", "@anthropic/mcp-filesystem", "/tmp"]
        )
        client = MCPClient(config)
        async with client:
            tools = await client.list_tools()
            result = await client.call_tool("read_file", {"path": "/tmp/test.txt"})
    """

    def __init__(self, config: MCPServerConfig):
        """Initialize MCP client.

        Args:
            config: Server configuration.
        """
        self.config = config
        self._session: Any = None  # mcp.ClientSession
        self._read_stream: Any = None
        self._write_stream: Any = None
        self._process: Optional[asyncio.subprocess.Process] = None
        self._connected = False
        self._tools: List[MCPTool] = []

    @property
    def connected(self) -> bool:
        """Check if the client is connected."""
        return self._connected

    @property
    def tools(self) -> List[MCPTool]:
        """Get cached list of tools."""
        return self._tools

    async def start(self) -> None:
        """Start the MCP server and establish connection.

        Raises:
            RuntimeError: If the server fails to start.
            ImportError: If the mcp package is not installed.
        """
        if self._connected:
            logger.warning(f"MCP client '{self.config.name}' already connected")
            return

        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as e:
            raise ImportError(
                "MCP package not installed. Install with: pip install mcp"
            ) from e

        if self.config.transport == "stdio":
            await self._start_stdio(ClientSession, StdioServerParameters, stdio_client)
        else:
            await self._start_sse()

    async def _start_stdio(
        self,
        ClientSession: type,
        StdioServerParameters: type,
        stdio_client: Any,
    ) -> None:
        """Start stdio transport connection."""
        server_params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=self.config.get_resolved_env() or None,
        )

        logger.info(
            f"Starting MCP server '{self.config.name}': "
            f"{self.config.command} {' '.join(self.config.args)}"
        )

        # Create the stdio client context
        self._stdio_context = stdio_client(server_params)
        self._read_stream, self._write_stream = await self._stdio_context.__aenter__()

        # Create and initialize session
        self._session = ClientSession(self._read_stream, self._write_stream)
        self._session_context = self._session.__aenter__()
        await self._session_context

        # Initialize the connection
        await self._session.initialize()
        self._connected = True

        # Cache tools
        await self._refresh_tools()

        logger.info(
            f"MCP server '{self.config.name}' connected with {len(self._tools)} tools"
        )

    async def _start_sse(self) -> None:
        """Start SSE transport connection."""
        try:
            from mcp import ClientSession
            from mcp.client.sse import sse_client
        except ImportError as e:
            raise ImportError(
                "MCP SSE client not available. Ensure mcp[sse] is installed."
            ) from e

        if not self.config.url:
            raise ValueError(f"MCP server '{self.config.name}': URL required for SSE")

        logger.info(f"Connecting to MCP server '{self.config.name}' at {self.config.url}")

        self._sse_context = sse_client(self.config.url)
        self._read_stream, self._write_stream = await self._sse_context.__aenter__()

        self._session = ClientSession(self._read_stream, self._write_stream)
        self._session_context = self._session.__aenter__()
        await self._session_context

        await self._session.initialize()
        self._connected = True

        await self._refresh_tools()

        logger.info(
            f"MCP server '{self.config.name}' connected via SSE with {len(self._tools)} tools"
        )

    async def stop(self) -> None:
        """Stop the MCP server connection."""
        if not self._connected:
            return

        logger.info(f"Stopping MCP server '{self.config.name}'")

        try:
            # Close session
            if self._session:
                try:
                    await self._session.__aexit__(None, None, None)
                except Exception as e:
                    logger.debug(f"Error closing session: {e}")
                self._session = None

            # Close transport
            if self.config.transport == "stdio" and hasattr(self, "_stdio_context"):
                try:
                    await self._stdio_context.__aexit__(None, None, None)
                except Exception as e:
                    logger.debug(f"Error closing stdio: {e}")
            elif self.config.transport == "sse" and hasattr(self, "_sse_context"):
                try:
                    await self._sse_context.__aexit__(None, None, None)
                except Exception as e:
                    logger.debug(f"Error closing SSE: {e}")

        except Exception as e:
            logger.error(f"Error stopping MCP server '{self.config.name}': {e}")
        finally:
            self._connected = False
            self._tools = []

    async def _refresh_tools(self) -> None:
        """Refresh the cached list of tools from the server."""
        if not self._session:
            return

        result = await self._session.list_tools()
        self._tools = [
            MCPTool(
                name=tool.name,
                description=tool.description or "",
                input_schema=tool.inputSchema if hasattr(tool, "inputSchema") else {},
            )
            for tool in result.tools
        ]

    async def list_tools(self) -> List[MCPTool]:
        """List available tools from the server.

        Returns:
            List of MCPTool objects.

        Raises:
            RuntimeError: If not connected.
        """
        if not self._connected:
            raise RuntimeError(f"MCP client '{self.config.name}' not connected")

        await self._refresh_tools()
        return self._tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> MCPToolResult:
        """Call a tool on the server.

        Args:
            tool_name: Name of the tool to call.
            arguments: Arguments to pass to the tool.

        Returns:
            MCPToolResult with the result or error.

        Raises:
            RuntimeError: If not connected.
        """
        if not self._connected or not self._session:
            raise RuntimeError(f"MCP client '{self.config.name}' not connected")

        try:
            result = await asyncio.wait_for(
                self._session.call_tool(tool_name, arguments or {}),
                timeout=self.config.timeout,
            )

            # Extract content from result
            content = self._extract_content(result)

            return MCPToolResult(
                success=not result.isError if hasattr(result, "isError") else True,
                content=content,
                is_error=result.isError if hasattr(result, "isError") else False,
            )

        except asyncio.TimeoutError:
            return MCPToolResult(
                success=False,
                error=f"Tool call timed out after {self.config.timeout}s",
            )
        except Exception as e:
            logger.error(f"Error calling tool '{tool_name}': {e}")
            return MCPToolResult(
                success=False,
                error=str(e),
            )

    def _extract_content(self, result: Any) -> Any:
        """Extract content from MCP result.

        Handles various content types (text, blob, etc.).
        """
        if not hasattr(result, "content") or not result.content:
            return None

        # If single content item, extract it
        if len(result.content) == 1:
            item = result.content[0]
            if hasattr(item, "text"):
                return item.text
            elif hasattr(item, "data"):
                return item.data
            return str(item)

        # Multiple content items - return as list
        contents = []
        for item in result.content:
            if hasattr(item, "text"):
                contents.append(item.text)
            elif hasattr(item, "data"):
                contents.append(item.data)
            else:
                contents.append(str(item))
        return contents

    async def __aenter__(self) -> "MCPClient":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.stop()


@asynccontextmanager
async def create_mcp_client(config: MCPServerConfig) -> AsyncIterator[MCPClient]:
    """Create and manage an MCP client lifecycle.

    Args:
        config: Server configuration.

    Yields:
        Connected MCPClient instance.
    """
    client = MCPClient(config)
    try:
        await client.start()
        yield client
    finally:
        await client.stop()
