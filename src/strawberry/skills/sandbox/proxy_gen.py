"""Proxy code generator for sandbox injection."""

import json
import logging
from enum import Enum
from typing import List, Optional

from ..loader import SkillInfo

logger = logging.getLogger(__name__)


class SkillMode(Enum):
    """Skill execution mode."""
    LOCAL = "local"    # Only local device skills (device)
    REMOTE = "remote"  # All devices via Hub (device_manager)


class ProxyGenerator:
    """Generates Python proxy code for injection into sandbox.

    The proxy code:
    - LOCAL mode: `device` object with local skill classes
    - REMOTE mode: `device_manager` object with all devices
    - Each method call bridges to the host for execution
    - Includes search_skills() and describe_function() helpers
    """

    def __init__(self, skills: List[SkillInfo], mode: SkillMode = SkillMode.LOCAL):
        """Initialize proxy generator.

        Args:
            skills: List of available skills (local skills for LOCAL mode)
            mode: LOCAL for device-only, REMOTE for device_manager
        """
        self.skills = skills
        self.mode = mode
        self._cache: Optional[str] = None

    def invalidate(self):
        """Invalidate cached proxy code (call after skill changes)."""
        self._cache = None

    def update_skills(self, skills: List[SkillInfo]):
        """Update skill list and invalidate cache."""
        self.skills = skills
        self._cache = None

    def set_mode(self, mode: SkillMode):
        """Change skill mode and invalidate cache."""
        if self.mode != mode:
            self.mode = mode
            self._cache = None

    def generate(self) -> str:
        """Generate Python proxy code based on current mode.

        Returns:
            Python code to inject into sandbox
        """
        if self._cache:
            return self._cache

        if self.mode == SkillMode.REMOTE:
            return self._generate_remote_mode()
        else:
            return self._generate_local_mode()

    def _generate_local_mode(self) -> str:
        """Generate LOCAL mode proxy code (device only)."""

        # Build skill metadata
        skill_data = []
        for skill in self.skills:
            skill_dict = {
                "name": skill.name,
                "methods": [
                    {
                        "name": m.name,
                        "signature": m.signature,
                        "docstring": m.docstring or "",
                    }
                    for m in skill.methods
                ]
            }
            skill_data.append(skill_dict)

        skill_data_json = json.dumps(skill_data)
        skill_names = [s.name for s in self.skills]

        # Generate the proxy code
        code = f'''# ============================================================================
# Auto-generated proxy code for Strawberry AI Sandbox
# DO NOT EDIT - This code is injected at runtime
# ============================================================================

import json
from pyodide.ffi import to_js

# Skill metadata (read-only)
_SKILL_DATA = {skill_data_json}

# Available skill names
_SKILL_NAMES = {skill_names!r}


def _bridge_call(path: str, args: list, kwargs: dict):
    """Call the host via JS bridge.

    This function is the only way to interact with the outside world.
    """
    # Convert Python objects to JS-compatible format
    js_args = to_js(args, dict_converter=lambda d: to_js(d))
    js_kwargs = to_js(kwargs, dict_converter=lambda d: to_js(d))

    # Call the JS bridge function (set up by host.ts)
    import asyncio
    result = _js_bridge_call(path, js_args, js_kwargs)

    # If it's a promise, we need to await it
    # Since Pyodide supports top-level await, this works
    return result


class _SkillMethodProxy:
    """Proxy for a single skill method."""

    def __init__(self, skill_name: str, method_name: str):
        self._skill_name = skill_name
        self._method_name = method_name

    def __call__(self, *args, **kwargs):
        path = f"{{self._skill_name}}.{{self._method_name}}"
        return _bridge_call(path, list(args), kwargs)


class _SkillProxy:
    """Proxy for a skill class."""

    def __init__(self, skill_name: str):
        self._skill_name = skill_name
        self._methods = {{}}

    def __getattr__(self, method_name: str):
        if method_name.startswith('_'):
            raise AttributeError(f"Cannot access private method: {{method_name}}")

        # Cache method proxies
        if method_name not in self._methods:
            self._methods[method_name] = _SkillMethodProxy(self._skill_name, method_name)
        return self._methods[method_name]


class _DeviceProxy:
    """Main device proxy - provides access to all skills."""

    def __init__(self):
        self._skills = {{}}
        self._skill_data = _SKILL_DATA

        # Pre-create skill proxies
        for name in _SKILL_NAMES:
            self._skills[name] = _SkillProxy(name)

    def __getattr__(self, name: str):
        if name.startswith('_'):
            raise AttributeError(f"Cannot access private attribute: {{name}}")

        if name in self._skills:
            return self._skills[name]

        available = ', '.join(self._skills.keys()) or 'None'
        raise AttributeError(f"Skill '{{name}}' not found. Available skills: {{available}}")

    def search_skills(self, query: str = "") -> list:
        """Search for skills by keyword.

        Args:
            query: Search term (matches name, signature, docstring)

        Returns:
            List of matching skills with path, signature, summary
        """
        results = []
        query_lower = query.lower() if query else ""

        for skill in self._skill_data:
            for method in skill["methods"]:
                if (not query or
                    query_lower in method["name"].lower() or
                    query_lower in skill["name"].lower() or
                    query_lower in method["docstring"].lower()):

                    summary = method["docstring"].split("\\n")[0] if method["docstring"] else ""
                    results.append({{
                        "path": f"{{skill['name']}}.{{method['name']}}",
                        "signature": method["signature"],
                        "summary": summary,
                    }})

        return results

    def describe_function(self, path: str) -> str:
        """Get full function details.

        Args:
            path: "SkillName.method_name"

        Returns:
            Full signature with docstring
        """
        parts = path.split(".")
        if len(parts) != 2:
            return f"Invalid path: {{path}}. Use format 'SkillName.method_name'"

        skill_name, method_name = parts

        for skill in self._skill_data:
            if skill["name"] == skill_name:
                for method in skill["methods"]:
                    if method["name"] == method_name:
                        signature = method["signature"]
                        doc = method["docstring"] or "No description available."
                        return (
                            f"def {{signature}}:\n"
                            f'    """{{doc}}"""'
                        )

                available_methods = ", ".join(m["name"] for m in skill["methods"])
                return (
                    f"Method '{{method_name}}' not found in {{skill_name}}. "
                    f"Available: {{available_methods}}"
                )

        available_skills = ", ".join(s["name"] for s in self._skill_data)
        return f"Skill '{{skill_name}}' not found. Available: {{available_skills}}"


# Create the global device instance
device = _DeviceProxy()

# Clean up module namespace - remove everything except what the LLM should use
del json
'''

        self._cache = code
        logger.debug(f"Generated LOCAL mode proxy code ({len(code)} bytes)")
        return code

    def _generate_remote_mode(self) -> str:
        """Generate REMOTE mode proxy code (device_manager).

        In remote mode, the LLM uses device_manager to access skills
        across all connected devices:

            device_manager.search_skills("volume")
            device_manager.TV.MediaSkill.set_volume(50)
            device_manager.describe_function("TV.MediaSkill.set_volume")
        """
        # Remote mode doesn't need local skill metadata - all calls go to host
        code = '''# ============================================================================
# Auto-generated proxy code for Strawberry AI Sandbox (REMOTE MODE)
# DO NOT EDIT - This code is injected at runtime
# ============================================================================

from pyodide.ffi import to_js


def _bridge_call(path: str, args: list, kwargs: dict):
    """Call the host via JS bridge.

    This function is the only way to interact with the outside world.
    """
    js_args = to_js(args, dict_converter=lambda d: to_js(d))
    js_kwargs = to_js(kwargs, dict_converter=lambda d: to_js(d))
    result = _js_bridge_call(path, js_args, js_kwargs)
    return result


class _RemoteMethodProxy:
    """Proxy for a remote skill method."""

    def __init__(self, device_name: str, skill_name: str, method_name: str):
        self._device_name = device_name
        self._skill_name = skill_name
        self._method_name = method_name

    def __call__(self, *args, **kwargs):
        # Path format: "remote:DeviceName.SkillClass.method"
        path = f"remote:{self._device_name}.{self._skill_name}.{self._method_name}"
        return _bridge_call(path, list(args), kwargs)


class _RemoteSkillProxy:
    """Proxy for a skill class on a remote device."""

    def __init__(self, device_name: str, skill_name: str):
        self._device_name = device_name
        self._skill_name = skill_name
        self._methods = {}

    def __getattr__(self, method_name: str):
        if method_name.startswith('_'):
            raise AttributeError(f"Cannot access private method: {method_name}")

        if method_name not in self._methods:
            self._methods[method_name] = _RemoteMethodProxy(
                self._device_name, self._skill_name, method_name
            )
        return self._methods[method_name]


class _RemoteDeviceProxy:
    """Proxy for a remote device."""

    def __init__(self, device_name: str):
        self._device_name = device_name
        self._skills = {}

    def __getattr__(self, skill_name: str):
        if skill_name.startswith('_'):
            raise AttributeError(f"Cannot access private attribute: {skill_name}")

        if skill_name not in self._skills:
            self._skills[skill_name] = _RemoteSkillProxy(self._device_name, skill_name)
        return self._skills[skill_name]


class _DeviceManagerProxy:
    """Main device manager proxy - provides access to all devices and skills.

    Usage:
        device_manager.search_skills("volume")
        device_manager.TV.MediaSkill.set_volume(50)
        device_manager.describe_function("TV.MediaSkill.set_volume")
    """

    def __init__(self):
        self._devices = {}

    def __getattr__(self, device_name: str):
        if device_name.startswith('_'):
            raise AttributeError(f"Cannot access private attribute: {device_name}")

        if device_name not in self._devices:
            self._devices[device_name] = _RemoteDeviceProxy(device_name)
        return self._devices[device_name]

    def search_skills(self, query: str = "") -> list:
        """Search for skills across all connected devices.

        Args:
            query: Search term (matches name, signature, docstring)

        Returns:
            List of matching skills with path, signature, summary, device
        """
        # Bridge to host for actual search
        return _bridge_call("devices.search_skills", [query], {})

    def describe_function(self, path: str) -> str:
        """Get full function details.

        Args:
            path: "DeviceName.SkillClass.method_name"

        Returns:
            Full signature with docstring
        """
        return _bridge_call("devices.describe_function", [path], {})


# Create the global devices instance (preferred name)
devices = _DeviceManagerProxy()

# Backward compatibility alias
device_manager = devices
'''

        self._cache = code
        logger.debug(f"Generated REMOTE mode proxy code ({len(code)} bytes)")
        return code

