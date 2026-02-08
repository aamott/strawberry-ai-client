"""Dynamically builds *Skill classes from MCP server tool definitions.

Each MCP server becomes a separate Skill class (e.g. HomeAssistantSkill),
and each MCP tool becomes a method on that class.
"""

import logging
import re
from typing import Any, Callable, Dict, List, Type

from .mcp_client import MCPServerInfo, MCPToolInfo

logger = logging.getLogger(__name__)


def _normalize_method_name(tool_name: str) -> str:
    """Normalise an MCP tool name into a valid Python identifier.

    Replaces hyphens and other non-alphanumeric characters with underscores
    so the method can be accessed via normal attribute syntax.

    Examples:
        "query-docs"        -> "query_docs"
        "resolve-library-id" -> "resolve_library_id"
        "HassTurnOn"        -> "HassTurnOn"  (already valid)

    Args:
        tool_name: Original MCP tool name.

    Returns:
        A valid Python identifier.
    """
    # Replace non-alphanumeric/underscore chars with underscores
    normalised = re.sub(r"[^a-zA-Z0-9_]", "_", tool_name)
    # Strip leading underscores / digits that would make it invalid
    normalised = re.sub(r"^[^a-zA-Z]+", "", normalised)
    return normalised or tool_name


def _server_name_to_class_name(server_name: str) -> str:
    """Convert an MCP server name to a PascalCase skill class name.

    Examples:
        "Home Assistant"   -> "HomeAssistantSkill"
        "context7"         -> "Context7Skill"
        "firebase"         -> "FirebaseSkill"
        "my-custom-server" -> "MyCustomServerSkill"

    Args:
        server_name: The human-readable server name from mcp_config.json.

    Returns:
        A PascalCase class name ending in 'Skill'.
    """
    # Replace non-alphanumeric with spaces, then PascalCase.
    # Use word[0].upper() + word[1:] instead of capitalize() to preserve
    # existing casing (e.g. "GitHub" stays "GitHub", not "Github").
    cleaned = re.sub(r"[^a-zA-Z0-9]", " ", server_name)
    parts = cleaned.split()
    pascal = "".join(word[0].upper() + word[1:] for word in parts if word)

    # Ensure it doesn't already end with 'Skill'
    if not pascal.endswith("Skill"):
        pascal += "Skill"

    return pascal


def _build_tool_docstring(tool: MCPToolInfo) -> str:
    """Build a docstring for a generated method from an MCP tool schema.

    Args:
        tool: The MCP tool info with name, description, and input schema.

    Returns:
        A Google-style docstring string.
    """
    lines = [tool.description or f"Call MCP tool '{tool.name}'."]

    # Parse input schema properties for Args section
    properties = tool.input_schema.get("properties", {})
    required = set(tool.input_schema.get("required", []))

    if properties:
        lines.append("")
        lines.append("Args:")
        for prop_name, prop_schema in properties.items():
            prop_type = prop_schema.get("type", "any")
            prop_desc = prop_schema.get("description", "")
            opt_marker = "" if prop_name in required else " (optional)"
            if prop_desc:
                lines.append(f"    {prop_name}: {prop_desc}{opt_marker}")
            else:
                lines.append(f"    {prop_name}: {prop_type}{opt_marker}")

    lines.append("")
    lines.append("Returns:")
    lines.append("    Result from the MCP tool call.")

    return "\n".join(lines)


def _json_schema_type_to_python(schema_type: str) -> str:
    """Map a JSON schema type string to a Python type hint string.

    Args:
        schema_type: JSON schema type (string, number, integer, boolean, array, object).

    Returns:
        Python type annotation as a string.
    """
    mapping = {
        "string": "str",
        "number": "float",
        "integer": "int",
        "boolean": "bool",
        "array": "list",
        "object": "dict",
    }
    return mapping.get(schema_type, "Any")


def _build_method_for_tool(
    tool: MCPToolInfo,
    call_tool_fn: Callable,
) -> Callable:
    """Create a method function that calls an MCP tool when invoked.

    The generated method accepts keyword arguments matching the tool's input
    schema, then delegates to `call_tool_fn` for the actual MCP call.

    Args:
        tool: MCP tool definition.
        call_tool_fn: Async function(tool_name, arguments) -> result.

    Returns:
        A bound-ready method (takes self as first arg).
    """
    tool_name = tool.name
    docstring = _build_tool_docstring(tool)
    properties = tool.input_schema.get("properties", {})
    required_params = set(tool.input_schema.get("required", []))

    def method(self: Any, **kwargs: Any) -> Any:
        """Placeholder — real docstring set below."""
        # Validate required params
        for param in required_params:
            if param not in kwargs:
                raise ValueError(
                    f"Missing required argument '{param}' for MCP tool '{tool_name}'"
                )

        # call_tool_fn is synchronous — it dispatches to the persistent
        # background event loop via run_coroutine_threadsafe().
        return call_tool_fn(tool_name, kwargs)

    # Set metadata — use a Python-safe identifier for __name__
    py_name = _normalize_method_name(tool_name)
    method.__name__ = py_name
    method.__qualname__ = py_name
    method.__doc__ = docstring

    # Build a proper signature with annotations for introspection
    annotations: Dict[str, Any] = {"return": Any}
    for prop_name, prop_schema in properties.items():
        py_type = _json_schema_type_to_python(prop_schema.get("type", "any"))
        annotations[prop_name] = py_type
    method.__annotations__ = annotations

    return method


def build_skill_class(
    server_info: MCPServerInfo,
    call_tool_fn: Callable,
    caller_module: str | None = None,
) -> Type:
    """Build a dynamic *Skill class for an MCP server.

    Args:
        server_info: Info about the server and its tools.
        call_tool_fn: Async function(tool_name, arguments) -> result string.
        caller_module: __module__ to assign to the class. The SkillLoader
            filters classes by obj.__module__ == module_name, so this must
            match the entrypoint module's fully-qualified name.

    Returns:
        A new class like HomeAssistantSkill with one method per tool.
    """
    class_name = _server_name_to_class_name(server_info.server_name)

    # Build class attributes: one method per tool
    attrs: Dict[str, Any] = {
        "__doc__": f"MCP skill for {server_info.server_name}. "
        f"Provides {len(server_info.tools)} tool(s).",
        "_mcp_server_name": server_info.server_name,
    }

    for tool in server_info.tools:
        method = _build_method_for_tool(tool, call_tool_fn)
        py_name = _normalize_method_name(tool.name)
        attrs[py_name] = method

    # Create the class dynamically
    skill_class = type(class_name, (), attrs)

    # Set __module__ so the SkillLoader recognises this class as belonging
    # to the entrypoint module (it filters on obj.__module__ == module_name).
    if caller_module:
        skill_class.__module__ = caller_module

    logger.info(
        "Built MCP skill class '%s' with %d methods from server '%s'",
        class_name,
        len(server_info.tools),
        server_info.server_name,
    )

    return skill_class


def build_all_skill_classes(
    servers: List[MCPServerInfo],
    call_tool_fns: Dict[str, Callable],
    caller_module: str | None = None,
) -> List[Type]:
    """Build skill classes for all discovered MCP servers.

    Args:
        servers: List of discovered server infos.
        call_tool_fns: Dict mapping server_name -> async call_tool function.
        caller_module: __module__ to assign to generated classes (see build_skill_class).

    Returns:
        List of dynamically created skill classes.
    """
    classes: List[Type] = []
    for server in servers:
        fn = call_tool_fns.get(server.server_name)
        if fn is None:
            logger.error(
                "No call_tool function for server '%s', skipping.",
                server.server_name,
            )
            continue
        cls = build_skill_class(server, fn, caller_module=caller_module)
        classes.append(cls)
    return classes
