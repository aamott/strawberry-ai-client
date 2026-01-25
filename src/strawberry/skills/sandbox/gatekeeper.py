"""Gatekeeper for validating and executing skill calls from sandbox."""

import logging
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from ..loader import SkillLoader

if TYPE_CHECKING:
    from ...mcp.registry import MCPRegistry
    from ..remote import DeviceManager

logger = logging.getLogger(__name__)


class SkillNotAllowedError(Exception):
    """Raised when a skill call is not in the allow-list."""
    pass


class Gatekeeper:
    """Validates and executes skill calls from the sandbox.

    Security:
    - Only allows registered skill methods
    - Logs all calls for audit
    - Sanitizes errors before returning

    Supports both local and remote modes:
    - Local: "SkillClass.method" → execute local skill
    - Remote: "remote:Device.Skill.method" → route to DeviceManager
    - Discovery: "device_manager.search_skills" → route to DeviceManager
    """

    def __init__(
        self,
        loader: SkillLoader,
        mcp_registry: Optional["MCPRegistry"] = None,
        device_manager: Optional["DeviceManager"] = None,
    ):
        """Initialize gatekeeper.

        Args:
            loader: SkillLoader with registered skills
            mcp_registry: Optional MCPRegistry for MCP server skills
            device_manager: Optional DeviceManager for remote calls
        """
        self.loader = loader
        self.mcp_registry = mcp_registry
        self.device_manager = device_manager
        self._allow_list: Set[str] = set()
        self._update_allow_list()

    def set_device_manager(self, device_manager: "DeviceManager"):
        """Set or update the device manager for remote calls.

        TODO: This method exists but is not currently called anywhere.
        The online/offline mode switching is handled differently:
        - SkillService uses _DeviceProxy (local) or _DeviceManagerProxy (online)
        - Mode is determined at initialization, not switched dynamically
        - Consider removing or integrating this if dynamic mode switching is needed.
        """
        self.device_manager = device_manager

    def _update_allow_list(self):
        """Rebuild allow-list from current skills (Python + MCP)."""
        self._allow_list.clear()

        # Add Python skills
        for skill in self.loader.get_all_skills():
            for method in skill.methods:
                path = f"{skill.name}.{method.name}"
                self._allow_list.add(path)

        # Add MCP skills
        if self.mcp_registry:
            for skill in self.mcp_registry.get_all_skills():
                for method in skill.methods:
                    path = f"{skill.name}.{method.name}"
                    self._allow_list.add(path)

        logger.info(f"Gatekeeper allow-list updated: {len(self._allow_list)} methods")
        logger.debug(f"Allow-list: {sorted(self._allow_list)}")

    def refresh(self):
        """Refresh allow-list (call after skill reload)."""
        self._update_allow_list()

    def get_allow_list(self) -> Set[str]:
        """Get the current allow-list (for debugging)."""
        return self._allow_list.copy()

    def is_allowed(self, path: str) -> bool:
        """Check if a skill path is allowed.

        Args:
            path: "SkillClass.method_name"

        Returns:
            True if allowed, False otherwise
        """
        return path in self._allow_list

    def execute(self, path: str, args: List[Any], kwargs: Dict[str, Any]) -> Any:
        """Execute a skill call.

        Args:
            path: Call path, one of:
                - "SkillClass.method" (local)
                - "remote:Device.Skill.method" (remote skill call)
                - "device_manager.search_skills" (remote discovery)
                - "device_manager.describe_function" (remote discovery)
            args: Positional arguments
            kwargs: Keyword arguments

        Returns:
            Result from skill execution

        Raises:
            SkillNotAllowedError: If path not in allow-list
            ValueError: If skill/method not found
            RuntimeError: If skill execution fails
        """
        # Handle remote mode calls
        if path.startswith("remote:"):
            return self._execute_remote(path[7:], args, kwargs)

        if path.startswith("device_manager."):
            return self._execute_device_manager(path[15:], args, kwargs)

        if path.startswith("devices."):
            return self._execute_device_manager(path[8:], args, kwargs)

        # Local mode - validate against allow-list
        if not self.is_allowed(path):
            logger.warning(f"Blocked skill call: {path}")
            raise SkillNotAllowedError(f"Skill not allowed: {path}")

        logger.info(f"Executing local skill: {path}(args={args}, kwargs={kwargs})")

        # Parse path
        parts = path.split(".")
        if len(parts) != 2:
            raise ValueError(f"Invalid path format: {path}")

        skill_name, method_name = parts

        # Check if this is an MCP skill (ends with MCP suffix)
        if skill_name.endswith("MCP") and self.mcp_registry:
            return self._execute_mcp(skill_name, method_name, args, kwargs)

        # Get skill info from Python loader
        skill_info = self.loader.get_skill(skill_name)
        if not skill_info:
            raise ValueError(f"Skill not found: {skill_name}")

        # Get skill instance
        if not skill_info.instance:
            raise ValueError(f"Skill has no instance: {skill_name}")

        # Get method
        method = getattr(skill_info.instance, method_name, None)
        if not method or not callable(method):
            raise ValueError(f"Method not found or not callable: {method_name}")

        # Execute
        try:
            result = method(*args, **kwargs)
            logger.debug(f"Skill result: {result!r}")
            return result

        except Exception as e:
            logger.error(f"Skill execution error: {path} - {e}")
            # Re-raise with sanitized message
            raise RuntimeError(self._sanitize_error(str(e)))

    def _execute_mcp(
        self,
        skill_name: str,
        method_name: str,
        args: List[Any],
        kwargs: Dict[str, Any],
    ) -> Any:
        """Execute an MCP tool call.

        Args:
            skill_name: MCP skill name (e.g., "BraveSearchMCP")
            method_name: Tool name
            args: Positional arguments (converted to kwargs)
            kwargs: Keyword arguments

        Returns:
            Result from MCP tool execution
        """
        if not self.mcp_registry:
            raise ValueError("MCP registry not configured")

        logger.info(f"Executing MCP tool: {skill_name}.{method_name}(kwargs={kwargs})")

        try:
            # MCP tools use kwargs only, convert args if needed
            if args:
                # Get tool schema to map positional args to param names
                skill_info = self.mcp_registry.get_skill(skill_name)
                if skill_info:
                    method_info = next(
                        (m for m in skill_info.methods if m.name == method_name), None
                    )
                    if method_info:
                        # Parse signature to get param names
                        # This is a simplified approach - just use kwargs
                        logger.warning(
                            f"MCP tool {skill_name}.{method_name} called with positional "
                            f"args {args}, converting to first kwarg"
                        )

            # Call through registry (sync wrapper)
            result = self.mcp_registry.call_method(skill_name, method_name, **kwargs)
            logger.debug(f"MCP tool result: {result!r}")
            return result

        except Exception as e:
            logger.error(f"MCP tool execution error: {skill_name}.{method_name} - {e}")
            raise RuntimeError(self._sanitize_error(str(e)))

    def _execute_remote(self, path: str, args: List[Any], kwargs: Dict[str, Any]) -> Any:
        """Execute a remote skill call via DeviceManager.

        Args:
            path: "DeviceName.SkillClass.method"
            args: Positional arguments
            kwargs: Keyword arguments
        """
        if not self.device_manager:
            raise ValueError("Remote mode not available - no DeviceManager configured")

        logger.info(f"Executing remote skill: {path}(args={args}, kwargs={kwargs})")

        parts = path.split(".")
        if len(parts) != 3:
            raise ValueError(f"Invalid remote path: {path}. Expected: Device.Skill.method")

        device_name, skill_name, method_name = parts

        try:
            # Get device proxy and call method
            device_proxy = getattr(self.device_manager, device_name)
            skill_proxy = getattr(device_proxy, skill_name)
            method_proxy = getattr(skill_proxy, method_name)
            result = method_proxy(*args, **kwargs)
            logger.debug(f"Remote skill result: {result!r}")
            return result

        except Exception as e:
            logger.error(f"Remote skill execution error: {path} - {e}")
            raise RuntimeError(self._sanitize_error(str(e)))

    def _execute_device_manager(self, method: str, args: List[Any], kwargs: Dict[str, Any]) -> Any:
        """Execute a DeviceManager method (search_skills, describe_function).

        Args:
            method: Method name (search_skills or describe_function)
            args: Positional arguments
            kwargs: Keyword arguments
        """
        if not self.device_manager:
            raise ValueError("Remote mode not available - no DeviceManager configured")

        logger.info(f"Executing device_manager.{method}(args={args}, kwargs={kwargs})")

        if method == "search_skills":
            query = args[0] if args else kwargs.get("query", "")
            return self.device_manager.search_skills(query)

        elif method == "describe_function":
            path = args[0] if args else kwargs.get("path", "")
            return self.device_manager.describe_function(path)

        else:
            raise ValueError(f"Unknown device_manager method: {method}")

    def _sanitize_error(self, error: str) -> str:
        """Remove sensitive info from error messages.

        Args:
            error: Raw error message

        Returns:
            Sanitized error message
        """
        # Remove file paths
        error = re.sub(r'File "[^"]+",', 'File "<skill>",', error)

        # Remove line numbers that might reveal structure
        error = re.sub(r'line \d+', 'line ?', error)

        # Limit length
        if len(error) > 500:
            error = error[:500] + "..."

        return error

