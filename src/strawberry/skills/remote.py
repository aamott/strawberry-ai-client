"""Remote skill execution via Hub.

Provides `device_manager` for accessing skills across all connected devices.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..hub import HubClient
from ..utils.async_bridge import run_sync

logger = logging.getLogger(__name__)


@dataclass
class RemoteSkillResult:
    """Result from searching remote skills.

    Skills are grouped by (class, method, signature) with a list of devices.
    """

    path: str  # "SkillClass.method" (without device prefix)
    signature: str
    summary: str
    docstring: str  # Full docstring
    devices: List[str]  # Normalized device names
    device_names: List[str]  # Display names
    device_count: int  # Total number of devices with this skill
    is_local: bool  # True if available on local device


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
        if method_name.startswith("_"):
            raise AttributeError(f"Cannot access private method: {method_name}")
        return RemoteSkillProxy(
            self._device_manager,
            self._device_name,
            self._skill_name,
            method_name,
        )


class LocalDeviceProxy:
    """Proxy for the local device - routes to local skill execution."""

    def __init__(self, local_loader: Any):
        self._local_loader = local_loader

    def __getattr__(self, skill_name: str):
        """Get a local skill proxy."""
        if skill_name.startswith("_"):
            raise AttributeError(f"Cannot access private attribute: {skill_name}")

        skill = self._local_loader.get_skill(skill_name)
        if skill is None:
            available = [s.name for s in self._local_loader.get_all_skills()]
            raise AttributeError(
                f"Skill '{skill_name}' not found locally. "
                f"Available: {', '.join(available)}"
            )
        return skill.instance


class RemoteDeviceProxy:
    """Proxy for a remote device."""

    def __init__(self, device_manager: "DeviceManager", device_name: str):
        self._device_manager = device_manager
        self._device_name = device_name
        self._skills: Dict[str, RemoteSkillClassProxy] = {}

    def __getattr__(self, skill_name: str) -> RemoteSkillClassProxy:
        if skill_name.startswith("_"):
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

    def __init__(
        self,
        hub_client: HubClient,
        local_device_name: str,
        local_loader: Optional[Any] = None,
    ):
        """Initialize device manager.

        Args:
            hub_client: Hub client for API calls
            local_device_name: Name of the local device (for prioritization)
            local_loader: Optional local skill loader for routing local device calls
        """
        self._hub_client = hub_client
        self._local_device_name = local_device_name
        self._local_loader = local_loader
        self._devices: Dict[str, RemoteDeviceProxy] = {}
        self._skill_cache: Optional[List[RemoteSkillResult]] = None
        self._cache_timestamp: float = 0
        self._cache_ttl: float = 60.0  # 1 minute cache
        self._cache_device_limit: int = 10

    def _supports_sync_method(self, method_name: str) -> bool:
        """Return True if the hub client provides a real sync implementation.

        We intentionally check the *type*, not the instance.

        Why:
        - In tests we often pass `Mock()` as the hub client.
        - `Mock` reports arbitrary attributes as present, so `hasattr(mock, "...")`
          is always True and would incorrectly route calls into a non-existent sync
          implementation.
        - Checking the class ensures we only use the sync fallback for real HubClient
          (or explicit stub classes that actually define the method).
        """
        try:
            attr = getattr(type(self._hub_client), method_name)
        except AttributeError:
            return False
        return callable(attr)

    def __getattr__(self, device_name: str):
        """Get proxy for a device (local or remote)."""
        if device_name.startswith("_"):
            raise AttributeError(f"Cannot access private attribute: {device_name}")

        # Check if this is the local device
        if device_name == self._local_device_name and self._local_loader:
            return LocalDeviceProxy(self._local_loader)

        # Otherwise create remote device proxy
        if device_name not in self._devices:
            self._devices[device_name] = RemoteDeviceProxy(self, device_name)
        return self._devices[device_name]

    def search_skills(
        self, query: str = "", device_limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Search for skills across all connected devices.

        Args:
            query: Search term (matches name, signature, docstring)
            device_limit: Number of sample devices to return per skill

        Returns:
            List of matching skills with path, signature, summary, device
        """
        import time

        # Check cache
        if (
            self._skill_cache is not None
            and time.time() - self._cache_timestamp < self._cache_ttl
            and device_limit <= self._cache_device_limit
        ):
            skills = self._skill_cache
        else:
            # Fetch from Hub
            try:
                skills = self._fetch_all_skills(device_limit=device_limit)
                self._skill_cache = skills
                self._cache_timestamp = time.time()
                self._cache_device_limit = device_limit
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
                if (
                    query_lower in skill.path.lower()
                    or query_lower in skill.signature.lower()
                    or query_lower in skill.summary.lower()
                ):
                    results.append(self._skill_to_dict(skill))

        # Prioritize local skills (already sorted by Hub, but ensure local first)
        results.sort(key=lambda s: 0 if s.get("is_local") else 1)

        return results

    def describe_function(self, path: str) -> str:
        """Get full function details.

        Args:
            path: "SkillClass.method_name" (skill path without device)

        Returns:
            Full signature with docstring
        """
        parts = path.split(".")
        if len(parts) != 2:
            return f"Invalid path: {path}. Use format 'SkillClass.method_name'"

        # Search for the skill in cache
        skills = self.search_skills()
        for skill in skills:
            if skill["path"] == path:
                # Return full docstring from cached data
                return self._fetch_function_details(path)

        return f"Function not found: {path}"

    def _fetch_all_skills(self, device_limit: int = 10) -> List[RemoteSkillResult]:
        """Fetch all skills from Hub.

        Returns grouped skills with device lists.
        """
        # IMPORTANT: Non-sandbox fallback (no Deno)
        #
        # DeviceManager methods are synchronous because they are often called from
        # the direct-exec fallback path (SkillService.execute_code). In that mode we
        # cannot safely rely on async objects bound to the UI/event loop.
        #
        # Prefer the HubClient's *sync* methods when available to avoid cross-event-loop
        # crashes. Fall back to the old async bridge for backward compatibility.
        if self._supports_sync_method("search_skills_sync"):
            skills_data = self._hub_client.search_skills_sync(
                query="",
                device_limit=device_limit,
            )
        else:
            skills_data = run_sync(
                self._hub_client.search_skills(query="", device_limit=device_limit)
            )

        results = []
        for skill in skills_data:
            results.append(
                RemoteSkillResult(
                    path=skill.get("path", ""),
                    signature=skill.get("signature", ""),
                    summary=skill.get("summary", ""),
                    docstring=skill.get("docstring", ""),
                    devices=skill.get("devices", []),
                    device_names=skill.get("device_names", []),
                    device_count=skill.get("device_count", 0),
                    is_local=skill.get("is_local", False),
                )
            )

        return results

    def _fetch_function_details(self, path: str) -> str:
        """Fetch full function details from Hub.

        Uses the full docstring from the cached skill data.
        """
        # Search in cached skills
        if self._skill_cache:
            for skill in self._skill_cache:
                if skill.path == path:
                    # Use full docstring if available, otherwise fall back to summary
                    doc = skill.docstring if skill.docstring else skill.summary
                    devices_info = f"Available on: {', '.join(skill.devices[:5])}"
                    if skill.device_count > 5:
                        devices_info += f" (+{skill.device_count - 5} more)"
                    return f'def {skill.signature}:\n    """{doc}"""\n\n# {devices_info}'

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
        try:
            # IMPORTANT: Non-sandbox fallback (no Deno)
            #
            # Prefer the sync HTTP path when available. This avoids event loop coupling
            # and makes remote skill calls work even when the Deno sandbox is missing.
            if self._supports_sync_method("execute_remote_skill_sync"):
                result = self._hub_client.execute_remote_skill_sync(
                    device_name=device_name,
                    skill_name=skill_name,
                    method_name=method_name,
                    args=list(args),
                    kwargs=kwargs,
                )
            else:
                result = run_sync(
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

    def _skill_to_dict(self, skill: RemoteSkillResult) -> Dict[str, Any]:
        """Convert RemoteSkillResult to dictionary."""
        return {
            "path": skill.path,
            "signature": skill.signature,
            "summary": skill.summary,
            "devices": skill.devices,
            "device_names": skill.device_names,
            "device_count": skill.device_count,
            "is_local": skill.is_local,
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
    'device_manager.search_skills(query: str = "") -> List[dict]\n'
    "# Search for skills across all devices\n"
    '# Returns: [{"path": "Skill.method", "signature": "...", '
    '"summary": "...", "devices": ["device1", ...], "device_count": N}]\n'
    "\n"
    "device_manager.describe_function(path: str) -> str\n"
    "# Get full function signature with docstring\n"
    '# Path format: "SkillClass.method_name"\n'
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
    'device.search_skills(query: str = "") -> List[dict]\n'
    "# Search for skills by keyword\n"
    '# Returns: [{"path": "Skill.method", "signature": "...", "summary": "..."}]\n'
    "\n"
    "device.describe_function(path: str) -> str\n"
    "# Get full function signature with docstring\n"
    '# Path format: "SkillClass.method_name"\n'
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

SWITCHED_TO_REMOTE_PROMPT = """<system>
Automated Message: The device switched to online mode
and now has access to skills on other devices.

The available tools have changed:
- device_manager.search_skills(query) - Search skills across all devices
- device_manager.describe_function(path) - Get function
  details (path: DeviceName.SkillClass.method)
- device_manager.DeviceName.SkillClass.method() - Call remote skill
</system>"""

SWITCHED_TO_LOCAL_PROMPT = """<system>
Automated Message: The device switched to offline mode. Only local skills are available.

The available tools have changed:
- device.search_skills(query) - Search local skills
- device.describe_function(path) - Get function details (path: SkillClass.method)
- device.SkillClass.method() - Call local skill
</system>"""
