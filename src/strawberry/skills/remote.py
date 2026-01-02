"""Remote skill execution via Hub.

Provides `device_manager` for accessing skills across all connected devices.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..hub import HubClient

logger = logging.getLogger(__name__)


@dataclass
class RemoteSkillResult:
    """Result from searching remote skills."""
    path: str  # "DeviceName.SkillClass.method"
    signature: str
    summary: str
    device: str  # Device name
    device_id: str  # Device ID


@dataclass
class RemoteExecutionResult:
    """Result from executing a remote skill."""
    success: bool
    result: Any = None
    error: Optional[str] = None
    device: Optional[str] = None


class RemoteSkillProxy:
    """Proxy for calling a remote skill method."""

    def __init__(
        self,
        device_manager: "DeviceManager",
        device_name: str,
        skill_name: str,
        method_name: str,
    ):
        self._device_manager = device_manager
        self._device_name = device_name
        self._skill_name = skill_name
        self._method_name = method_name

    def __call__(self, *args, **kwargs) -> Any:
        """Execute the remote skill call."""
        path = f"{self._device_name}.{self._skill_name}.{self._method_name}"
        return self._device_manager._execute_remote(path, args, kwargs)


class RemoteSkillClassProxy:
    """Proxy for a skill class on a remote device."""

    def __init__(
        self,
        device_manager: "DeviceManager",
        device_name: str,
        skill_name: str,
    ):
        self._device_manager = device_manager
        self._device_name = device_name
        self._skill_name = skill_name

    def __getattr__(self, method_name: str) -> RemoteSkillProxy:
        if method_name.startswith('_'):
            raise AttributeError(f"Cannot access private method: {method_name}")
        return RemoteSkillProxy(
            self._device_manager,
            self._device_name,
            self._skill_name,
            method_name,
        )


class RemoteDeviceProxy:
    """Proxy for a remote device."""

    def __init__(self, device_manager: "DeviceManager", device_name: str):
        self._device_manager = device_manager
        self._device_name = device_name
        self._skills: Dict[str, RemoteSkillClassProxy] = {}

    def __getattr__(self, skill_name: str) -> RemoteSkillClassProxy:
        if skill_name.startswith('_'):
            raise AttributeError(f"Cannot access private attribute: {skill_name}")

        if skill_name not in self._skills:
            self._skills[skill_name] = RemoteSkillClassProxy(
                self._device_manager,
                self._device_name,
                skill_name,
            )
        return self._skills[skill_name]


class DeviceManager:
    """Manages access to skills across all connected devices.

    Provides:
    - device_manager.search_skills(query) - Search skills on all devices
    - device_manager.describe_function(path) - Get function details
    - device_manager.DeviceName.SkillClass.method() - Call remote skill
    """

    def __init__(self, hub_client: HubClient, local_device_name: str):
        """Initialize device manager.

        Args:
            hub_client: Hub client for API calls
            local_device_name: Name of the local device (for prioritization)
        """
        self._hub_client = hub_client
        self._local_device_name = local_device_name
        self._devices: Dict[str, RemoteDeviceProxy] = {}
        self._skill_cache: Optional[List[RemoteSkillResult]] = None
        self._cache_timestamp: float = 0
        self._cache_ttl: float = 60.0  # 1 minute cache

    def __getattr__(self, device_name: str) -> RemoteDeviceProxy:
        """Get proxy for a remote device."""
        if device_name.startswith('_'):
            raise AttributeError(f"Cannot access private attribute: {device_name}")

        if device_name not in self._devices:
            self._devices[device_name] = RemoteDeviceProxy(self, device_name)
        return self._devices[device_name]

    def search_skills(self, query: str = "") -> List[Dict[str, Any]]:
        """Search for skills across all connected devices.

        Args:
            query: Search term (matches name, signature, docstring)

        Returns:
            List of matching skills with path, signature, summary, device
        """
        import time

        # Check cache
        if (self._skill_cache is not None and
            time.time() - self._cache_timestamp < self._cache_ttl):
            skills = self._skill_cache
        else:
            # Fetch from Hub
            try:
                skills = self._fetch_all_skills()
                self._skill_cache = skills
                self._cache_timestamp = time.time()
            except Exception as e:
                logger.error(f"Failed to fetch skills: {e}")
                return []

        # Filter by query
        if not query:
            results = [self._skill_to_dict(s) for s in skills]
        else:
            query_lower = query.lower()
            results = []

            for skill in skills:
                if (query_lower in skill.path.lower() or
                    query_lower in skill.signature.lower() or
                    query_lower in skill.summary.lower()):
                    results.append(self._skill_to_dict(skill))

        # Prioritize local device (sort so local comes first)
        results.sort(key=lambda s: 0 if s["device"] == self._local_device_name else 1)

        return results

    def describe_function(self, path: str) -> str:
        """Get full function details.

        Args:
            path: "DeviceName.SkillClass.method_name"

        Returns:
            Full signature with docstring
        """
        parts = path.split(".")
        if len(parts) != 3:
            return f"Invalid path: {path}. Use format 'DeviceName.SkillClass.method_name'"

        device_name, skill_name, method_name = parts

        # Search for the skill
        skills = self.search_skills()
        for skill in skills:
            if skill["path"] == path:
                # Fetch full docstring from Hub
                try:
                    return self._fetch_function_details(path)
                except Exception as e:
                    logger.error(f"Failed to fetch function details: {e}")
                    return f"def {skill['signature']}:\n    \"\"\"{skill['summary']}\"\"\""

        return f"Function not found: {path}"

    def _fetch_all_skills(self) -> List[RemoteSkillResult]:
        """Fetch all skills from Hub."""
        # Run async in sync context
        loop = asyncio.new_event_loop()
        try:
            skills_data = loop.run_until_complete(
                self._hub_client.list_skills()
            )
        finally:
            loop.close()

        results = []
        for skill in skills_data:
            results.append(RemoteSkillResult(
                path=f"{skill['device_name']}.{skill['class_name']}.{skill['function_name']}",
                signature=skill.get('signature', ''),
                summary=(skill.get('docstring', '') or '').split('\n')[0],
                device=skill['device_name'],
                device_id=skill.get('device_id', ''),
            ))

        return results

    def _fetch_function_details(self, path: str) -> str:
        """Fetch full function details from Hub."""
        parts = path.split(".")
        if len(parts) != 3:
            return f"Invalid path: {path}"

        device_name, skill_name, method_name = parts

        # Search in cached skills
        if self._skill_cache:
            for skill in self._skill_cache:
                if skill.path == path:
                    return f"def {skill.signature}:\n    \"\"\"{skill.summary}\"\"\""

        return f"Function not found: {path}"

    def _execute_remote(self, path: str, args: tuple, kwargs: dict) -> Any:
        """Execute a remote skill call via Hub.

        Args:
            path: "DeviceName.SkillClass.method_name"
            args: Positional arguments
            kwargs: Keyword arguments

        Returns:
            Result from remote execution
        """
        parts = path.split(".")
        if len(parts) != 3:
            raise ValueError(f"Invalid skill path: {path}")

        device_name, skill_name, method_name = parts

        # Execute via Hub
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                self._hub_client.execute_remote_skill(
                    device_name=device_name,
                    skill_name=skill_name,
                    method_name=method_name,
                    args=list(args),
                    kwargs=kwargs,
                )
            )
            return result
        except Exception as e:
            logger.error(f"Remote skill execution failed: {e}")
            raise RuntimeError(f"Failed to execute {path}: {e}")
        finally:
            loop.close()

    def _skill_to_dict(self, skill: RemoteSkillResult) -> Dict[str, Any]:
        """Convert RemoteSkillResult to dictionary."""
        return {
            "path": skill.path,
            "signature": skill.signature,
            "summary": skill.summary,
            "device": skill.device,
        }

    def invalidate_cache(self):
        """Invalidate the skill cache."""
        self._skill_cache = None
        self._cache_timestamp = 0


# Mode switching prompts
REMOTE_MODE_PROMPT = (
    "You are Strawberry, a helpful AI assistant with access to skills across all "
    "connected devices.\n"
    "\n"
    "## How Remote Skills Work\n"
    "\n"
    "When you write a ```python code block, I will execute it and show you the output. "
    "Then you continue your response.\n"
    "\n"
    "## Available Functions\n"
    "\n"
    "```python\n"
    "device_manager: DeviceManager  # Manages all connected devices\n"
    "\n"
    "device_manager.search_skills(query: str = \"\") -> List[dict]\n"
    "# Search for skills across all devices\n"
    "# Returns: [{\"path\": \"Device.Skill.method\", \"signature\": \"...\", "
    "\"summary\": \"...\", \"device\": \"...\"}]\n"
    "\n"
    "device_manager.describe_function(path: str) -> str\n"
    "# Get full function signature with docstring\n"
    "# Path format: \"DeviceName.SkillClass.method_name\"\n"
    "\n"
    "device_manager.DeviceName.SkillClass.method(...)\n"
    "# Call a skill on a specific device\n"
    "```\n"
    "\n"
    "## Rules\n"
    "\n"
    "1. Always wrap code in ```python fences\n"
    "2. Always use print() to see output\n"
    "3. After I show you the output, respond naturally to the user\n"
    "4. Search for skills first if you're not sure what's available"
)

LOCAL_MODE_PROMPT = (
    "You are Strawberry, a helpful AI assistant with access to skills on this device.\n"
    "\n"
    "## How Skills Work\n"
    "\n"
    "When you write a ```python code block, I will execute it and show you the output. "
    "Then you continue your response.\n"
    "\n"
    "## Available Functions\n"
    "\n"
    "```python\n"
    "device: Device  # Container for local skills\n"
    "\n"
    "device.search_skills(query: str = \"\") -> List[dict]\n"
    "# Search for skills by keyword\n"
    "# Returns: [{\"path\": \"Skill.method\", \"signature\": \"...\", \"summary\": \"...\"}]\n"
    "\n"
    "device.describe_function(path: str) -> str\n"
    "# Get full function signature with docstring\n"
    "# Path format: \"SkillClass.method_name\"\n"
    "\n"
    "device.SkillClass.method(...)\n"
    "# Call a skill directly\n"
    "```\n"
    "\n"
    "## Rules\n"
    "\n"
    "1. Always wrap code in ```python fences\n"
    "2. Always use print() to see output\n"
    "3. After I show you the output, respond naturally to the user\n"
    "4. Search for skills first if you're not sure what's available"
)

SWITCHED_TO_REMOTE_PROMPT = '''<system>
Automated Message: The device switched to online mode and now has access to skills on other devices.

The available tools have changed:
- device_manager.search_skills(query) - Search skills across all devices
- device_manager.describe_function(path) - Get function details (path: DeviceName.SkillClass.method)
- device_manager.DeviceName.SkillClass.method() - Call remote skill
</system>'''

SWITCHED_TO_LOCAL_PROMPT = '''<system>
Automated Message: The device switched to offline mode. Only local skills are available.

The available tools have changed:
- device.search_skills(query) - Search local skills
- device.describe_function(path) - Get function details (path: SkillClass.method)
- device.SkillClass.method() - Call local skill
</system>'''

