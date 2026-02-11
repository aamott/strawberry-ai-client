"""Storage backends for settings persistence.

This module provides storage classes for persisting settings to YAML files
and environment files (.env).
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class YamlStorage:
    """YAML file storage for non-secret settings.

    Stores settings in a nested YAML structure organized by namespace.

    Example file structure:
        spoke_core:
          device:
            name: "My PC"
          hub:
            url: "https://hub.example.com"
        voice_core:
          stt:
            order: "leopard,whisper"
    """

    def __init__(self, path: Path):
        """Initialize YAML storage.

        Args:
            path: Path to the YAML file.
        """
        self._path = path

    @property
    def path(self) -> Path:
        """Get the storage file path."""
        return self._path

    def load(self) -> Dict[str, Dict[str, Any]]:
        """Load all settings from YAML file.

        Returns:
            Dictionary of namespace -> {key: value} mappings.
        """
        if not self._path.exists():
            return {}

        try:
            with open(self._path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return self._flatten_namespaces(data)
        except yaml.YAMLError as e:
            logger.warning(f"Failed to load settings from {self._path}: {e}")
            return {}

    def save(self, data: Dict[str, Dict[str, Any]]) -> None:
        """Save all settings to YAML file.

        Args:
            data: Dictionary of namespace -> {key: value} mappings.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # Convert flat keys to nested structure for readability
        nested_data = self._unflatten_namespaces(data)

        with open(self._path, "w", encoding="utf-8") as f:
            yaml.dump(nested_data, f, default_flow_style=False, sort_keys=False)

    def set(self, namespace: str, key: str, value: Any) -> None:
        """Set a single value (loads, modifies, saves).

        Args:
            namespace: The namespace (e.g., "spoke_core").
            key: The setting key (e.g., "hub.url").
            value: The value to set.
        """
        data = self.load()
        if namespace not in data:
            data[namespace] = {}
        data[namespace][key] = value
        self.save(data)

    def _flatten_namespaces(self, data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Convert nested YAML to flat namespace -> {key: value} structure.

        Args:
            data: Nested YAML data.

        Returns:
            Flattened structure.
        """
        result: Dict[str, Dict[str, Any]] = {}

        for namespace, ns_data in data.items():
            if isinstance(ns_data, dict):
                result[namespace] = self._flatten_dict(ns_data)
            else:
                # Handle non-dict namespace values
                result[namespace] = {"_value": ns_data}

        return result

    def _flatten_dict(self, d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
        """Flatten a nested dictionary using dot-notation keys.

        Args:
            d: Dictionary to flatten.
            prefix: Key prefix for nested keys.

        Returns:
            Flattened dictionary.
        """
        result = {}
        for key, value in d.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                result.update(self._flatten_dict(value, full_key))
            else:
                result[full_key] = value
        return result

    def _unflatten_namespaces(self, data: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Convert flat namespace -> {key: value} to nested YAML structure.

        Args:
            data: Flattened structure.

        Returns:
            Nested YAML-friendly structure.
        """
        result: Dict[str, Any] = {}

        for namespace, ns_data in data.items():
            result[namespace] = self._unflatten_dict(ns_data)

        return result

    def _unflatten_dict(self, d: Dict[str, Any]) -> Dict[str, Any]:
        """Unflatten a dictionary with dot-notation keys.

        Args:
            d: Flattened dictionary.

        Returns:
            Nested dictionary.
        """
        result: Dict[str, Any] = {}
        for key, value in d.items():
            parts = key.split(".")
            current = result
            for part in parts[:-1]:
                # If path doesn't exist or is not a dict (e.g. was None), create it
                if part not in current or not isinstance(current[part], dict):
                    current[part] = {}
                current = current[part]
            current[parts[-1]] = value
        return result


class EnvStorage:
    """Environment file (.env) storage for secrets.

    Stores sensitive settings like API keys and tokens in a .env file.
    Environment variables use the format: NAMESPACE__KEY (double underscore).

    Example:
        SPOKE_CORE__HUB__TOKEN=abc123
        VOICE_STT_WHISPER__ACCESS_KEY=xyz789
    """

    def __init__(self, path: Path):
        """Initialize environment storage.

        Args:
            path: Path to the .env file.
        """
        self._path = path
        if path.exists():
            load_dotenv(path, override=True)

    @property
    def path(self) -> Path:
        """Get the storage file path."""
        return self._path

    def load(self) -> Dict[str, str]:
        """Load all values from .env file.

        Returns:
            Dictionary of environment variable names to values.
        """
        if not self._path.exists():
            return {}

        values = {}
        try:
            with open(self._path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip()
                        # Remove surrounding quotes
                        if (value.startswith('"') and value.endswith('"')) or (
                            value.startswith("'") and value.endswith("'")
                        ):
                            value = value[1:-1]
                        values[key] = value
        except OSError as e:
            logger.warning(f"Failed to load .env from {self._path}: {e}")

        return values

    def save(self, data: Dict[str, str]) -> None:
        """Save all secrets to .env file.

        Args:
            data: Dictionary of environment variable names to values.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)

        existing_lines = self._read_raw_lines()
        seen_keys: set[str] = set()
        written_keys: set[str] = set()
        output_lines: List[str] = []
        duplicate_keys: set[str] = set()

        for raw_line in existing_lines:
            line = raw_line.rstrip("\n")
            stripped = line.strip()

            # Preserve comments/blank/unknown lines untouched
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                output_lines.append(line)
                continue

            key, _, current_value = line.partition("=")
            key = key.strip()

            if key in seen_keys:
                duplicate_keys.add(key)
                continue  # drop later duplicates to avoid multiple definitions

            seen_keys.add(key)

            if key in data:
                new_value = self._format_env_value(data[key])
                output_lines.append(f"{key}={new_value}")
                written_keys.add(key)
            else:
                output_lines.append(line)

        # Append new keys not present in the original file
        for key, value in data.items():
            if key in written_keys:
                continue
            output_lines.append(f"{key}={self._format_env_value(value)}")

        if duplicate_keys:
            logger.warning(
                "Removed duplicate env keys during save: %s",
                ", ".join(sorted(duplicate_keys)),
            )

        with open(self._path, "w", encoding="utf-8") as f:
            f.write("\n".join(output_lines))
            if output_lines:
                f.write("\n")

    def set(self, key: str, value: Any) -> None:
        """Set a single environment variable.

        Args:
            key: Environment variable name.
            value: Value to set.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)

        str_value = str(value) if value is not None else ""

        # Preserve comments/ordering by using our comment-aware save path.
        # This avoids rewriting the entire file in a way that can drop user
        # organization.
        self.save({key: str_value})

        # Also update the current environment
        os.environ[key] = str_value

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get an environment variable value.

        Args:
            key: Environment variable name.
            default: Default value if not set.

        Returns:
            The value or default.
        """
        # Check current environment first (may have been set programmatically)
        value = os.environ.get(key)
        if value is not None:
            return value

        # Fall back to loading from file
        data = self.load()
        return data.get(key, default)

    def _read_raw_lines(self) -> List[str]:
        """Read raw lines from the .env file preserving comments and blanks."""

        if not self._path.exists():
            return []

        try:
            with open(self._path, encoding="utf-8") as f:
                return f.readlines()
        except OSError as e:
            logger.warning(f"Failed to read .env from {self._path}: {e}")
            return []

    @staticmethod
    def _format_env_value(value: Any) -> str:
        """Format an env value with minimal quoting to preserve readability."""

        text = "" if value is None else str(value)
        if text and (" " in text or '"' in text or "'" in text):
            escaped = text.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        return text

    def delete(self, key: str) -> None:
        """Delete an environment variable.

        Args:
            key: Environment variable name to delete.
        """
        # Remove from current environment
        os.environ.pop(key, None)

        # Remove from file
        data = self.load()
        if key in data:
            del data[key]
            self.save(data)


def namespace_to_env_key(namespace: str, key: str) -> str:
    """Convert namespace and key to environment variable format.

    Args:
        namespace: The namespace (e.g., "voice.stt.whisper").
        key: The setting key (e.g., "access_key").

    Returns:
        Environment variable name (e.g., "VOICE_STT_WHISPER__ACCESS_KEY").
    """
    ns_part = namespace.upper().replace(".", "_")
    key_part = key.upper().replace(".", "__")
    return f"{ns_part}__{key_part}"


def parse_list_value(value: Any) -> list:
    """Parse a value that should be a list.

    Handles backward compatibility with CSV strings stored in older configs.

    Args:
        value: The value to parse (list, CSV string, or other).

    Returns:
        List of items.
    """
    if isinstance(value, list):
        return value
    if value is None:
        return []
    if isinstance(value, str):
        # Handle CSV strings for backward compatibility
        if "," in value:
            return [item.strip() for item in value.split(",") if item.strip()]
        # Single value
        return [value] if value.strip() else []
    # Other types - wrap in list
    return [value]


def env_key_to_namespace(
    env_key: str, known_namespaces: list[str]
) -> tuple[Optional[str], str]:
    """Convert environment variable name back to namespace and key.

    Args:
        env_key: Environment variable name.
        known_namespaces: List of registered namespace names.

    Returns:
        Tuple of (namespace, key) or (None, "") if can't parse.
    """
    # Sort by length descending to match most specific namespace first
    # This prevents ambiguities when one namespace is a prefix of another
    # e.g., "voice" vs "voice.stt.whisper"
    sorted_namespaces = sorted(known_namespaces, key=len, reverse=True)

    for namespace in sorted_namespaces:
        prefix = namespace.upper().replace(".", "_") + "__"
        if env_key.startswith(prefix):
            key = env_key[len(prefix) :].lower().replace("__", ".")
            return namespace, key

    return None, ""
