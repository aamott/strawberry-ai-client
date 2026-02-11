"""Proxy classes for LLM-generated code to access skills.

These proxies provide the ``device.*`` and ``devices.*`` / ``device_manager.*``
namespaces that the LLM uses inside ``python_exec`` calls.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from ..hub import HubClient
    from .loader import SkillLoader

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def normalize_device_name(name: str) -> str:
    """Normalize a device name for consistent routing.

    Transforms device names into a canonical form:
    - Lowercased
    - Spaces/hyphens converted to underscores
    - Special characters removed
    - Unicode normalized to ASCII equivalents

    This implementation must stay in sync with the Hub's
    ``hub.utils.normalize_device_name``.  The canonical test vectors
    live in ``docs/test-fixtures/normalize_device_name.json``.

    Args:
        name: Raw device name (display name).

    Returns:
        Normalized name suitable for routing.
    """
    if not name:
        return ""

    # Normalize unicode (é -> e, ü -> u, etc.)
    normalized = unicodedata.normalize("NFKD", name)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")

    # Lowercase
    normalized = normalized.lower()

    # Replace spaces and hyphens with underscores
    normalized = re.sub(r"[\s\-]+", "_", normalized)

    # Remove non-alphanumeric characters (except underscores)
    normalized = re.sub(r"[^a-z0-9_]", "", normalized)

    # Collapse multiple underscores
    normalized = re.sub(r"_+", "_", normalized)

    # Strip leading/trailing underscores
    normalized = normalized.strip("_")

    return normalized


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SkillCallResult:
    """Result of executing a skill call."""

    success: bool
    result: Any = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Search helpers
# ---------------------------------------------------------------------------

# Common English stop words to strip from search queries.
# Prevents "turn on the lamp" from matching everything via "the" or "on".
_SEARCH_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "to",
        "for",
        "of",
        "in",
        "on",
        "it",
        "and",
        "or",
        "my",
        "me",
        "i",
        "do",
        "can",
        "you",
        "please",
        "what",
        "how",
        "get",
        "set",
    }
)


# ---------------------------------------------------------------------------
# Local device proxies
# ---------------------------------------------------------------------------


class DeviceProxy:
    """Proxy object for accessing skills from LLM-generated code.

    Provides:
    - device.search_skills("query") - Find skills by keyword
    - device.describe_function("SkillName.method") - Get function details
    - device.SkillName.method_name(args) - Call a skill
    """

    def __init__(self, loader: SkillLoader):
        """Initialize the device proxy.

        Args:
            loader: Skill loader used to resolve skills.
        """
        self._loader = loader

    def search_skills(
        self, query: str = "", device_limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Search for skills by keyword.

        Splits the query into words and matches if **any** word appears
        in the method name, skill name, signature, or docstring.  This
        makes multi-word queries like "react documentation" find results
        that match on "documentation" alone.

        Args:
            query: Search term (matches name, signature, docstring)
            device_limit: Ignored for local-only mode

        Returns:
            List of matching skills with path, signature, summary
        """
        query_words = self._parse_query_words(query)
        candidates = self._build_search_candidates(query_words)
        matched = self._match_candidates(candidates, query_words)

        results = []
        for skill, method in matched:
            summary = ""
            if method.docstring:
                summary = method.docstring.split("\n")[0].strip()
            results.append(
                {
                    "path": f"{skill.name}.{method.name}",
                    "signature": method.signature,
                    "summary": summary,
                }
            )
        return results

    @staticmethod
    def _parse_query_words(query: str) -> list[str]:
        """Parse a query into search words, stripping stop words."""
        raw_words = query.lower().split() if query else []
        query_words = [w for w in raw_words if w not in _SEARCH_STOP_WORDS]
        # Fall back to original words if stop-word stripping removed everything
        if not query_words and raw_words:
            query_words = raw_words
        return query_words

    def _build_search_candidates(
        self,
        query_words: list[str],
    ) -> list[tuple]:
        """Build (skill, method, searchable_text) triples."""
        candidates: list[tuple] = []
        for skill in self._loader.get_all_skills():
            for method in skill.methods:
                if not query_words:
                    candidates.append((skill, method, True))
                else:
                    searchable = (
                        f"{method.name} {skill.name} "
                        f"{method.signature} "
                        f"{method.docstring or ''}"
                    ).lower()
                    candidates.append((skill, method, searchable))
        return candidates

    @staticmethod
    def _match_candidates(
        candidates: list[tuple],
        query_words: list[str],
    ) -> list[tuple]:
        """Match candidates against query words (all-words first, then any-word)."""
        if not query_words:
            return [(s, m) for s, m, _ in candidates]

        matched = [
            (s, m)
            for s, m, txt in candidates
            if txt is True or all(w in txt for w in query_words)
        ]
        if not matched:
            matched = [
                (s, m)
                for s, m, txt in candidates
                if txt is True or any(w in txt for w in query_words)
            ]
        return matched

    def describe_function(self, path: str) -> str:
        """Get full function details including docstring.

        Args:
            path: "SkillName.method_name"

        Returns:
            Full function signature with docstring
        """
        # Import here to avoid circular dependency
        from .prompt import build_example_call

        parts = path.split(".")
        if len(parts) != 2:
            return f"Error: Invalid path '{path}'. Use format 'SkillName.method_name'"

        skill_name, method_name = parts
        skill = self._loader.get_skill(skill_name)

        if not skill:
            return f"Error: Skill '{skill_name}' not found"

        for method in skill.methods:
            if method.name == method_name:
                doc = method.docstring or "No description available"
                example = build_example_call(skill_name, method)
                result = f'def {method.signature}:\n    """\n    {doc}\n    """'
                if example:
                    result += f'\n\nExample:\n  python_exec(code="{example}")'
                return result

        return f"Error: Method '{method_name}' not found in {skill_name}"

    def __getattr__(self, name: str):
        """Get a skill class by name for direct calls."""
        # Don't intercept private attributes
        if name.startswith("_"):
            raise AttributeError(name)

        skill = self._loader.get_skill(name)
        if skill is None:
            # Get list of available skills for helpful error
            available = [s.name for s in self._loader.get_all_skills()]
            available_str = ", ".join(available) if available else "none loaded"
            raise AttributeError(
                f"Skill '{name}' not found. "
                f"Available skills: {available_str}. "
                f"Use device.search_skills() to search."
            )
        return SkillProxy(self._loader, name)


class SkillProxy:
    """Proxy for a specific skill class."""

    def __init__(self, loader: SkillLoader, skill_name: str):
        """Initialize a proxy for a single skill.

        Args:
            loader: Skill loader used to resolve methods.
            skill_name: Skill class name.
        """
        self._loader = loader
        self._skill_name = skill_name

    def __getattr__(self, name: str):
        """Get a method that calls the actual skill."""

        def method_wrapper(*args, **kwargs):
            return self._loader.call_method(self._skill_name, name, *args, **kwargs)

        return method_wrapper


# ---------------------------------------------------------------------------
# Multi-device proxies (online/Hub mode)
# ---------------------------------------------------------------------------


class DeviceManagerProxy:
    """Proxy object for accessing skills across multiple devices (online mode).

    Provides:
    - device_manager.search_skills("query") - Find skills across all devices
    - device_manager.describe_function("device.SkillName.method") - Get function details
    - device_manager.device_name.SkillName.method(args) - Call skill on specific device

    Uses __getattr__ for dynamic device access so devices can connect/disconnect
    during a chat session.
    """

    def __init__(
        self,
        local_loader: SkillLoader,
        hub_client: Optional[HubClient] = None,
        connected_devices: Optional[Dict[str, Dict[str, Any]]] = None,
        local_device_name: Optional[str] = None,
    ):
        """Initialize device manager proxy.

        Args:
            local_loader: Local skill loader for this device
            hub_client: Hub client for remote skill calls
            connected_devices: Dict mapping device_name -> device_info with skills
            local_device_name: Name of the local device (will be normalized)
        """
        self._local_loader = local_loader
        self._hub_client = hub_client
        self._connected_devices: Dict[str, Dict[str, Any]] = connected_devices or {}
        self._local_device_name = (
            normalize_device_name(local_device_name) if local_device_name else "local"
        )

    def set_local_device_name(self, name: str) -> None:
        """Set the name of the local device."""
        self._local_device_name = normalize_device_name(name)

    def update_connected_devices(self, devices: Dict[str, Dict[str, Any]]) -> None:
        """Update the list of connected devices and their skills.

        Args:
            devices: Dict mapping device_name -> {"skills": [...], "online": bool}
        """
        self._connected_devices = {
            normalize_device_name(k): v for k, v in devices.items()
        }

    def search_skills(
        self, query: str = "", device_limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Search for skills across all connected devices.

        Args:
            query: Search term (matches name, signature, docstring)

        Returns:
            List of skills with path, signature, summary, and devices list
        """
        device_limit = max(1, min(int(device_limit or 10), 100))
        skill_map: Dict[str, Dict[str, Any]] = {}

        self._add_local_skills(query, skill_map)
        self._add_remote_skills(query, skill_map, device_limit)

        return list(skill_map.values())

    def _add_local_skills(
        self,
        query: str,
        skill_map: Dict[str, Dict[str, Any]],
    ) -> None:
        """Add matching local skills to the skill map."""
        query_lower = query.lower() if query else ""
        for skill in self._local_loader.get_all_skills():
            for method in skill.methods:
                if not self._skill_matches(
                    query_lower,
                    method.name,
                    skill.name,
                    method.signature,
                    method.docstring or "",
                ):
                    continue
                key = f"{skill.name}.{method.name}"
                summary = (method.docstring or "").split("\n")[0].strip()
                if key not in skill_map:
                    skill_map[key] = {
                        "path": key,
                        "signature": method.signature,
                        "summary": summary,
                        "devices": [],
                        "device_count": 0,
                    }
                if self._local_device_name not in skill_map[key]["devices"]:
                    skill_map[key]["devices"].append(self._local_device_name)
                skill_map[key]["device_count"] += 1

    def _add_remote_skills(
        self,
        query: str,
        skill_map: Dict[str, Dict[str, Any]],
        device_limit: int,
    ) -> None:
        """Add matching remote device skills to the skill map."""
        query_lower = query.lower() if query else ""
        for device_name, device_info in self._connected_devices.items():
            if not device_info.get("online", False):
                continue
            for skill_data in device_info.get("skills", []):
                skill_name = skill_data.get("class_name", "")
                method_name = skill_data.get("function_name", "")
                signature = skill_data.get("signature", "")
                docstring = skill_data.get("docstring", "")
                if not self._skill_matches(
                    query_lower,
                    method_name,
                    skill_name,
                    signature,
                    docstring,
                ):
                    continue
                key = f"{skill_name}.{method_name}"
                summary = docstring.split("\n")[0].strip() if docstring else ""
                if key not in skill_map:
                    skill_map[key] = {
                        "path": key,
                        "signature": signature,
                        "summary": summary,
                        "devices": [],
                        "device_count": 0,
                    }
                skill_map[key]["device_count"] += 1
                if (
                    device_name not in skill_map[key]["devices"]
                    and len(skill_map[key]["devices"]) < device_limit
                ):
                    skill_map[key]["devices"].append(device_name)

    @staticmethod
    def _skill_matches(
        query_lower: str,
        method_name: str,
        skill_name: str,
        signature: str,
        docstring: str,
    ) -> bool:
        """Return True if a skill method matches the search query."""
        if not query_lower:
            return True
        return (
            query_lower in method_name.lower()
            or query_lower in skill_name.lower()
            or query_lower in signature.lower()
            or query_lower in docstring.lower()
        )

    def describe_function(self, path: str) -> str:
        """Get full function details including docstring.

        Args:
            path: "device_name.SkillName.method_name" or "SkillName.method_name"

        Returns:
            Full function signature with docstring
        """
        parts = path.split(".")

        if len(parts) == 2:
            skill_name, method_name = parts
            return self._describe_local_method(skill_name, method_name)

        elif len(parts) == 3:
            device_name, skill_name, method_name = parts
            device_name = normalize_device_name(device_name)

            # Local device
            if device_name == self._local_device_name:
                result = self._describe_local_method(skill_name, method_name)
                if not result.startswith("Error:"):
                    return result

            # Remote devices
            device_info = self._connected_devices.get(device_name)
            if device_info:
                for skill_data in device_info.get("skills", []):
                    if (
                        skill_data.get("class_name") == skill_name
                        and skill_data.get("function_name") == method_name
                    ):
                        sig = skill_data.get("signature", f"{method_name}()")
                        doc = skill_data.get("docstring", "No description available")
                        return f'def {sig}:\n    """\n    {doc}\n    """'

            return f"Error: Function '{path}' not found"

        return (
            f"Error: Invalid path '{path}'."
            " Use 'SkillName.method' or"
            " 'device.SkillName.method'"
        )

    def _describe_local_method(self, skill_name: str, method_name: str) -> str:
        """Describe a method from the local skill loader."""
        skill = self._local_loader.get_skill(skill_name)
        if skill:
            for method in skill.methods:
                if method.name == method_name:
                    doc = method.docstring or "No description available"
                    return f'def {method.signature}:\n    """\n    {doc}\n    """'
        return f"Error: Method '{method_name}' not found in {skill_name}"

    def __getattr__(self, name: str) -> "RemoteDeviceProxy":
        """Get a device by name for skill calls.

        Uses __getattr__ so devices can connect/disconnect during conversation.
        """
        if name.startswith("_"):
            raise AttributeError(name)

        normalized = normalize_device_name(name)

        # Check if it's the local device
        if normalized == self._local_device_name:
            return LocalDeviceSkillsProxy(self._local_loader)

        # Check if device exists in connected devices
        if normalized not in self._connected_devices:
            available = list(self._connected_devices.keys())
            if self._local_device_name:
                available.insert(0, self._local_device_name)
            available_str = ", ".join(available) if available else "none connected"
            raise AttributeError(
                f"Device '{name}' not connected. "
                f"Available devices: {available_str}. "
                f"Use device_manager.search_skills() to see all skills."
            )

        device_info = self._connected_devices[normalized]
        if not device_info.get("online", False):
            raise AttributeError(f"Device '{name}' is currently offline.")

        return RemoteDeviceProxy(normalized, self._hub_client)


class LocalDeviceSkillsProxy:
    """Proxy for accessing local device skills through device_manager."""

    def __init__(self, loader: SkillLoader):
        """Initialize the local device proxy.

        Args:
            loader: Skill loader used to resolve skills.
        """
        self._loader = loader

    def __getattr__(self, skill_name: str) -> "SkillProxy":
        """Resolve a skill class by name.

        Args:
            skill_name: Skill class name.

        Returns:
            Skill proxy for invoking methods.
        """
        if skill_name.startswith("_"):
            raise AttributeError(skill_name)
        skill = self._loader.get_skill(skill_name)
        if skill is None:
            available = [s.name for s in self._loader.get_all_skills()]
            raise AttributeError(
                f"Skill '{skill_name}' not found. Available: {', '.join(available)}"
            )
        return SkillProxy(self._loader, skill_name)


class RemoteDeviceProxy:
    """Proxy for accessing skills on a remote device."""

    def __init__(self, device_name: str, hub_client: Optional[HubClient]):
        """Initialize the remote device proxy.

        Args:
            device_name: Normalized device name.
            hub_client: Hub client used for remote calls.
        """
        self._device_name = device_name
        self._hub_client = hub_client

    def __getattr__(self, skill_name: str) -> "RemoteSkillProxy":
        """Resolve a remote skill by name.

        Args:
            skill_name: Skill class name.

        Returns:
            Proxy for the remote skill.
        """
        if skill_name.startswith("_"):
            raise AttributeError(skill_name)
        return RemoteSkillProxy(self._device_name, skill_name, self._hub_client)


class RemoteSkillProxy:
    """Proxy for a skill on a remote device."""

    def __init__(
        self, device_name: str, skill_name: str, hub_client: Optional[HubClient]
    ):
        """Initialize the remote skill proxy.

        Args:
            device_name: Target device name.
            skill_name: Skill class name.
            hub_client: Hub client used for remote calls.
        """
        self._device_name = device_name
        self._skill_name = skill_name
        self._hub_client = hub_client

    def __getattr__(self, method_name: str):
        """Get a method that calls the remote skill."""
        if method_name.startswith("_"):
            raise AttributeError(method_name)

        def method_wrapper(*args, **kwargs):
            if not self._hub_client:
                raise RuntimeError("Hub client not available for remote skill calls")

            # This will be called synchronously from sandbox
            # The actual call goes through Hub to the target device
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                # No running loop: use asyncio.run() so the loop is always closed.
                return asyncio.run(
                    self._hub_client.execute_remote_skill(
                        device_name=self._device_name,
                        skill_name=self._skill_name,
                        method_name=method_name,
                        args=list(args),
                        kwargs=kwargs,
                    )
                )

            # Running loop in this thread.
            # Remote skill calls from sandbox require async bridge implementation.
            raise NotImplementedError(
                "Remote skill calls from sandbox require async bridge implementation. "
                f"Attempted: {self._device_name}.{self._skill_name}.{method_name}"
            )

        return method_wrapper
