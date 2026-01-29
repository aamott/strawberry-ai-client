"""MCP to Skill adapter.

This module converts MCP tools into the SkillInfo/SkillMethod format used
by the rest of the Strawberry skill system. This is the MODULARITY POINT:
if we switch from Python skill signatures to TypeScript, we only need to
change this adapter.

The adapter:
1. Takes an MCPClient with its list of Tools
2. Produces a SkillInfo that looks like a Python skill class
3. Creates SkillMethod objects for each tool with proper signatures
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

if TYPE_CHECKING:
    from mcp.types import Tool

    from .client import MCPClient

# Import SkillInfo and SkillMethod from the skills module
from ..skills.loader import SkillInfo, SkillMethod

logger = logging.getLogger(__name__)


class MCPSkillAdapter:
    """Converts MCP servers/tools to SkillInfo/SkillMethod format.

    This adapter is the bridge between MCP's tool definitions and Strawberry's
    skill system. It allows MCP tools to be presented to the LLM exactly like
    Python skill classes.

    The adapter generates:
    - A SkillInfo for each MCP server (the "class")
    - A SkillMethod for each MCP tool (the "method")

    Example:
        >>> adapter = MCPSkillAdapter()
        >>> skill_info = adapter.adapt_server(mcp_client)
        >>> # skill_info.name = "HomeAssistantMCP"
        >>> # skill_info.methods = [SkillMethod(name="turn_on_light", ...), ...]
    """

    def adapt_server(self, client: "MCPClient") -> SkillInfo:
        """Convert an MCP server into a SkillInfo.

        Creates a SkillInfo that represents the MCP server as a skill class.
        Each tool becomes a method on this "class".

        Args:
            client: The MCPClient with loaded tools.

        Returns:
            A SkillInfo representing the MCP server.
        """
        skill_name = client.skill_class_name

        # Convert each MCP tool to a SkillMethod
        methods: List[SkillMethod] = []
        for tool in client.tools:
            method = self.adapt_tool(tool, client)
            methods.append(method)

        # Create a dummy class object for compatibility with SkillInfo
        # This class is never instantiated - calls go through MCPClient
        mcp_class = self._create_mcp_class(skill_name, client)

        skill_info = SkillInfo(
            name=skill_name,
            class_obj=mcp_class,
            methods=methods,
            module_path=None,  # MCP servers don't have a file path
            instance=None,  # No instance - calls route to MCPClient
        )

        logger.debug(
            f"Adapted MCP server '{client.name}' as skill '{skill_name}' "
            f"with {len(methods)} methods"
        )

        return skill_info

    def adapt_tool(self, tool: "Tool", client: "MCPClient") -> SkillMethod:
        """Convert an MCP tool into a SkillMethod.

        Creates a SkillMethod with:
        - Name: The tool's name
        - Signature: Generated from the tool's input schema
        - Docstring: The tool's description
        - Callable: A wrapper that calls MCPClient.call_tool

        Args:
            tool: The MCP Tool object.
            client: The MCPClient for creating the callable wrapper.

        Returns:
            A SkillMethod representing the tool.
        """
        # Generate a Python-style signature from the JSON schema
        signature = self._schema_to_signature(tool.name, tool.inputSchema)

        # Get docstring from tool description
        docstring = tool.description or f"MCP tool: {tool.name}"

        # Create a callable that wraps MCPClient.call_tool
        # This is used by the Gatekeeper when routing calls
        callable_wrapper = self._create_tool_callable(tool.name, client)

        return SkillMethod(
            name=tool.name,
            signature=signature,
            docstring=docstring,
            callable=callable_wrapper,
        )

    def _schema_to_signature(
        self, tool_name: str, input_schema: Optional[Dict[str, Any]]
    ) -> str:
        """Convert a JSON schema to a Python function signature.

        This is the key conversion that makes MCP tools look like Python methods.
        We generate signatures like:
            turn_on_light(entity_id: str, brightness: int = 100) -> Any

        Args:
            tool_name: The tool/method name.
            input_schema: The JSON schema for the tool's input.

        Returns:
            A Python-style signature string.
        """
        if not input_schema:
            return f"{tool_name}() -> Any"

        # Extract properties and required fields from schema
        properties = input_schema.get("properties", {})
        required = set(input_schema.get("required", []))

        # Build parameter list
        params: List[str] = []
        for param_name, param_info in properties.items():
            param_type = self._json_type_to_python(param_info.get("type", "any"))
            is_required = param_name in required

            if is_required:
                params.append(f"{param_name}: {param_type}")
            else:
                # Include default value hint for optional params
                default = param_info.get("default", "...")
                if isinstance(default, str):
                    default = f'"{default}"'
                params.append(f"{param_name}: {param_type} = {default}")

        params_str = ", ".join(params)
        return f"{tool_name}({params_str}) -> Any"

    def _json_type_to_python(self, json_type: str) -> str:
        """Convert JSON schema type to Python type hint.

        Args:
            json_type: JSON schema type (string, number, etc.).

        Returns:
            Python type hint string.
        """
        type_map = {
            "string": "str",
            "number": "float",
            "integer": "int",
            "boolean": "bool",
            "array": "List",
            "object": "Dict",
            "null": "None",
        }
        return type_map.get(json_type, "Any")

    def _create_mcp_class(self, class_name: str, client: "MCPClient") -> type:
        """Create a dummy class type for the MCP server.

        The class is only used for type compatibility with SkillInfo.
        The actual method calls are routed through MCPClient.

        Args:
            class_name: The skill class name (e.g., "HomeAssistantMCP").
            client: The MCPClient this class represents.

        Returns:
            A dynamically created class type.
        """

        # Create a class with a docstring describing the MCP server
        class_dict = {
            "__doc__": f"MCP server: {client.name}",
            "__mcp_client__": client,  # Store reference for routing
        }

        # Add method stubs for each tool (for introspection)
        for tool in client.tools:

            def make_method(tool_name: str) -> Callable:
                """Create a method stub that shows it's an MCP tool."""

                async def method_stub(self, **kwargs) -> Any:
                    """MCP tool - calls are routed through MCPClient."""
                    raise NotImplementedError(
                        f"Direct calls not supported. Use MCPClient.call_tool('{tool_name}', ...)"
                    )

                method_stub.__name__ = tool_name
                method_stub.__doc__ = tool.description
                return method_stub

            class_dict[tool.name] = make_method(tool.name)

        # Dynamically create the class
        return type(class_name, (), class_dict)

    def _create_tool_callable(
        self, tool_name: str, client: "MCPClient"
    ) -> Callable[..., Any]:
        """Create a callable wrapper for an MCP tool.

        This callable is stored in SkillMethod.callable and used by the
        Gatekeeper to execute the tool. It wraps MCPClient.call_tool.

        Args:
            tool_name: The tool name.
            client: The MCPClient to call.

        Returns:
            A callable that invokes the MCP tool.
        """

        async def tool_callable(**kwargs: Any) -> Any:
            """Execute the MCP tool through the client.

            Args:
                **kwargs: Tool arguments.

            Returns:
                Tool execution result.
            """
            return await client.call_tool(tool_name, kwargs)

        tool_callable.__name__ = tool_name
        return tool_callable


def is_mcp_skill(skill_info: SkillInfo) -> bool:
    """Check if a SkillInfo represents an MCP server.

    Args:
        skill_info: The skill info to check.

    Returns:
        True if this is an MCP skill (name ends with "MCP").
    """
    return skill_info.name.endswith("MCP")


def get_mcp_client_from_skill(skill_info: SkillInfo) -> Optional["MCPClient"]:
    """Get the MCPClient from an MCP skill's class object.

    Args:
        skill_info: An MCP skill info.

    Returns:
        The MCPClient, or None if not an MCP skill.
    """
    if not is_mcp_skill(skill_info):
        return None

    return getattr(skill_info.class_obj, "__mcp_client__", None)
