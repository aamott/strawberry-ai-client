"""Adapter to convert MCP tools to SkillInfo format."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from strawberry.skills.loader import SkillInfo, SkillMethod

from strawberry.mcp.client import MCPTool

logger = logging.getLogger(__name__)

# JSON Schema type to Python type hint mapping
JSON_TYPE_MAP = {
    "string": "str",
    "number": "float",
    "integer": "int",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
    "null": "None",
}


class MCPSkillAdapter:
    """Converts MCP tools to SkillInfo format for unified skill discovery.

    This adapter makes MCP servers appear as regular skills to the rest of
    the system, enabling:
    - Unified search via search_skills()
    - Consistent calling pattern: device.<ServerName>MCP.<tool>()
    - Documentation in system prompts

    Example:
        adapter = MCPSkillAdapter()
        skill_info = adapter.as_skill_info("brave-search", tools)
        # skill_info.name == "BraveSearchMCP"
        # skill_info.methods contains SkillMethod objects for each tool
    """

    def as_skill_info(
        self,
        server_name: str,
        tools: List[MCPTool],
        description: Optional[str] = None,
    ) -> "SkillInfo":
        """Convert MCP tools to a SkillInfo object.

        Args:
            server_name: MCP server name (e.g., "brave-search").
            tools: List of MCPTool objects from the server.
            description: Optional description for the skill class.

        Returns:
            SkillInfo with methods derived from MCP tools.
        """
        # Lazy import to avoid circular dependency
        from strawberry.skills.loader import SkillInfo

        skill_name = self._to_skill_name(server_name)

        methods = []
        for tool in tools:
            method = self._tool_to_method(tool)
            if method:
                methods.append(method)

        # Create a dummy class for documentation purposes
        class_doc = description or f"MCP server: {server_name}"

        # We can't create a real class, but SkillInfo needs class_obj
        # Create a simple placeholder class with the docstring
        placeholder_class = type(
            skill_name,
            (),
            {"__doc__": class_doc},
        )

        return SkillInfo(
            name=skill_name,
            class_obj=placeholder_class,
            methods=methods,
            module_path=None,
            instance=None,  # No instance - calls go through MCPRegistry
        )

    def _tool_to_method(self, tool: MCPTool) -> Optional["SkillMethod"]:
        """Convert an MCP tool to a SkillMethod.

        Args:
            tool: MCPTool to convert.

        Returns:
            SkillMethod or None if conversion fails.
        """
        # Lazy import to avoid circular dependency
        from strawberry.skills.loader import SkillMethod

        try:
            signature = self._schema_to_signature(tool.name, tool.input_schema)
            docstring = tool.description or f"MCP tool: {tool.name}"

            return SkillMethod(
                name=tool.name,
                signature=signature,
                docstring=docstring,
                callable=None,  # Not a real Python callable
            )
        except Exception as e:
            logger.warning(f"Failed to convert tool '{tool.name}': {e}")
            return None

    def _schema_to_signature(self, name: str, schema: Dict[str, Any]) -> str:
        """Convert JSON Schema to Python-like signature.

        Args:
            name: Tool name.
            schema: JSON Schema for the tool's input.

        Returns:
            Python function signature string.

        Example:
            schema = {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "count": {"type": "integer", "default": 10}
                },
                "required": ["query"]
            }
            -> "search(query: str, count: int = 10)"
        """
        if not schema or schema.get("type") != "object":
            return f"{name}(**kwargs)"

        properties = schema.get("properties", {})
        required = set(schema.get("required", []))

        params = []
        # Process required parameters first
        for prop_name in sorted(properties.keys(), key=lambda x: x not in required):
            prop_schema = properties[prop_name]
            py_type = self._json_type_to_python(prop_schema)

            if prop_name in required:
                params.append(f"{prop_name}: {py_type}")
            else:
                default = prop_schema.get("default")
                default_repr = self._format_default(default)
                params.append(f"{prop_name}: {py_type} = {default_repr}")

        return f"{name}({', '.join(params)})"

    def _json_type_to_python(self, prop_schema: Dict[str, Any]) -> str:
        """Convert JSON Schema type to Python type hint.

        Args:
            prop_schema: JSON Schema property definition.

        Returns:
            Python type hint string.
        """
        json_type = prop_schema.get("type", "any")

        # Handle array with items
        if json_type == "array":
            items = prop_schema.get("items", {})
            item_type = self._json_type_to_python(items)
            return f"List[{item_type}]"

        # Handle oneOf/anyOf (union types)
        if "oneOf" in prop_schema or "anyOf" in prop_schema:
            types = prop_schema.get("oneOf") or prop_schema.get("anyOf", [])
            py_types = [self._json_type_to_python(t) for t in types]
            # Remove duplicates and None
            unique_types = list(dict.fromkeys(t for t in py_types if t != "None"))
            if len(unique_types) == 1:
                return unique_types[0]
            return f"Union[{', '.join(unique_types)}]"

        # Handle enum
        if "enum" in prop_schema:
            return "str"  # Simplify to str for LLM

        return JSON_TYPE_MAP.get(json_type, "Any")

    def _format_default(self, default: Any) -> str:
        """Format a default value for signature display.

        Args:
            default: Default value from schema.

        Returns:
            String representation for signature.
        """
        if default is None:
            return "None"
        elif isinstance(default, str):
            return repr(default)
        elif isinstance(default, bool):
            return str(default)
        elif isinstance(default, (int, float)):
            return str(default)
        elif isinstance(default, list):
            return "[]" if not default else repr(default)
        elif isinstance(default, dict):
            return "{}" if not default else repr(default)
        else:
            return repr(default)

    def _to_skill_name(self, server_name: str) -> str:
        """Convert server name to skill name.

        Args:
            server_name: MCP server name (e.g., "brave-search").

        Returns:
            Skill name in PascalCase with MCP suffix (e.g., "BraveSearchMCP").
        """
        # Split by hyphens and underscores
        parts = re.split(r"[-_]", server_name)
        # Capitalize each part and join
        pascal = "".join(part.capitalize() for part in parts)
        return f"{pascal}MCP"

    def _to_server_name(self, skill_name: str) -> str:
        """Convert skill name back to server name.

        Args:
            skill_name: Skill name (e.g., "BraveSearchMCP").

        Returns:
            Server name in kebab-case (e.g., "brave-search").
        """
        # Remove MCP suffix
        if skill_name.endswith("MCP"):
            skill_name = skill_name[:-3]

        # Convert PascalCase to kebab-case
        # Insert hyphen before uppercase letters, then lowercase
        kebab = re.sub(r"(?<!^)(?=[A-Z])", "-", skill_name).lower()
        return kebab
