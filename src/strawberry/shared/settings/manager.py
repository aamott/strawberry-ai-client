"""Centralized settings manager with namespace isolation.

This module provides the SettingsManager class that manages settings for
multiple modules (SpokeCore, VoiceCore, backends, etc.) with namespace
isolation.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .schema import ActionResult, SettingField
from .storage import (
    EnvStorage,
    YamlStorage,
    env_key_to_namespace,
    namespace_to_env_key,
)

logger = logging.getLogger(__name__)


@dataclass
class RegisteredNamespace:
    """Metadata for a registered settings namespace.

    Attributes:
        name: Unique identifier (e.g., "spoke_core", "voice.stt.whisper").
        display_name: Human-readable name for UI (e.g., "Spoke Core").
        schema: List of SettingField definitions.
        order: Display order in UI (lower = first).
    """

    name: str
    display_name: str
    schema: List[SettingField]
    order: int = 100


class SettingsManager:
    """Centralized settings service with namespace isolation.

    Provides a single point of access for all application settings,
    organized by namespace. Each module (SpokeCore, VoiceCore, backends)
    registers its own namespace with schema.

    Example:
        # Initialize once at app startup
        settings = SettingsManager(config_dir=Path("config"))

        # Register namespaces
        settings.register("spoke_core", "Spoke Core", SPOKE_CORE_SCHEMA, order=10)
        settings.register("voice_core", "Voice", VOICE_CORE_SCHEMA, order=20)

        # Get/set values
        hub_url = settings.get("spoke_core", "hub.url")
        settings.set("spoke_core", "hub.url", "https://my-hub.com")

        # Listen for changes
        settings.on_change(lambda ns, key, val: print(f"{ns}.{key} = {val}"))
    """

    def __init__(
        self,
        config_dir: Path,
        auto_save: bool = True,
        yaml_filename: str = "settings.yaml",
        env_filename: str = ".env",
    ):
        """Initialize the settings manager.

        Args:
            config_dir: Directory containing settings files.
            auto_save: If True, persist changes immediately.
            yaml_filename: Name of the YAML settings file.
            env_filename: Name of the .env secrets file.
        """
        self._config_dir = Path(config_dir)
        self._auto_save = auto_save

        # Storage backends
        self._yaml_storage = YamlStorage(self._config_dir / yaml_filename)
        self._env_storage = EnvStorage(self._config_dir / env_filename)

        # Registered namespaces and their schemas
        self._namespaces: Dict[str, RegisteredNamespace] = {}

        # In-memory values (namespace -> {key: value})
        self._values: Dict[str, Dict[str, Any]] = {}

        # Change listeners
        self._listeners: List[Callable[[str, str, Any], None]] = []

        # Options providers for DYNAMIC_SELECT fields
        self._options_providers: Dict[str, Callable[[], List[str]]] = {}

        # Action handlers for ACTION fields
        self._action_handlers: Dict[str, Callable[[str, str], Any]] = {}

        # External validators: (namespace, key) -> callable(value) -> Optional[str]
        self._validators: Dict[str, Callable[[Any], Optional[str]]] = {}

        # Load existing values from storage
        self._load()

    @property
    def config_dir(self) -> Path:
        """Get the configuration directory path."""
        return self._config_dir

    # ─────────────────────────────────────────────────────────────────
    # Registration
    # ─────────────────────────────────────────────────────────────────

    def register(
        self,
        namespace: str,
        display_name: str,
        schema: List[SettingField],
        order: int = 100,
    ) -> None:
        """Register a settings namespace with its schema.

        Args:
            namespace: Unique identifier (e.g., "spoke_core", "voice.stt.whisper").
            display_name: Human-readable name for UI (e.g., "Spoke Core").
            schema: List of SettingField definitions.
            order: Display order in UI (lower = first).

        Raises:
            ValueError: If namespace is already registered.
        """
        if namespace in self._namespaces:
            raise ValueError(f"Namespace '{namespace}' already registered")

        self._namespaces[namespace] = RegisteredNamespace(
            name=namespace,
            display_name=display_name,
            schema=schema,
            order=order,
        )

        # Initialize values with defaults if not already loaded
        if namespace not in self._values:
            self._values[namespace] = {}

        # Apply defaults for missing values and load secrets from env
        # Apply Defaults
        for field in schema:
            if field.key not in self._values[namespace]:
                self._values[namespace][field.key] = field.default

            # Load secrets with custom env_key from environment variables (os.environ)
            # This handles explicit overrides defined in schema (e.g. API keys)
            if field.secret and field.env_key:
                env_value = self._env_storage.get(field.env_key)
                if env_value:
                    self._values[namespace][field.key] = env_value
                    logger.debug(f"Loaded secret '{field.key}' from env var '{field.env_key}'")

        # Apply Env Overrides from .env file
        # This handles standard NAMESPACE__KEY variables for this namespace
        env_data = self._env_storage.load()
        for env_key, value in env_data.items():
            # Check if this env var belongs to THIS namespace
            ns, k = env_key_to_namespace(env_key, [namespace])
            if ns == namespace:
                self._values[namespace][k] = value
                logger.debug(f"Loaded override '{k}' from env var '{env_key}'")

        logger.debug(f"Registered settings namespace: {namespace}")

    def unregister(self, namespace: str) -> None:
        """Remove a registered namespace.

        Note: Values remain in memory but won't be schema-validated.

        Args:
            namespace: The namespace to remove.
        """
        self._namespaces.pop(namespace, None)
        logger.debug(f"Unregistered settings namespace: {namespace}")

    def is_registered(self, namespace: str) -> bool:
        """Check if a namespace is registered.

        Args:
            namespace: The namespace to check.

        Returns:
            True if registered, False otherwise.
        """
        return namespace in self._namespaces

    # ─────────────────────────────────────────────────────────────────
    # Value Access
    # ─────────────────────────────────────────────────────────────────

    def get(self, namespace: str, key: str, default: Any = None) -> Any:
        """Get a setting value.

        Args:
            namespace: The namespace (e.g., "spoke_core").
            key: The setting key within namespace (e.g., "hub.url").
            default: Value to return if not set.

        Returns:
            The setting value or default.
        """
        ns_values = self._values.get(namespace, {})

        # Check if key exists (not just if value is truthy) to allow None as valid value
        if key not in ns_values:
            # Try to get default from schema
            field = self.get_field(namespace, key)
            if field is not None:
                return field.default if default is None else default
            return default

        return ns_values[key]

    def get_all(self, namespace: str) -> Dict[str, Any]:
        """Get all settings for a namespace.

        Args:
            namespace: The namespace.

        Returns:
            Dict of all settings in the namespace.
        """
        return dict(self._values.get(namespace, {}))

    def set(
        self,
        namespace: str,
        key: str,
        value: Any,
        skip_validation: bool = False,
        save: bool = True,
    ) -> Optional[str]:
        """Set a setting value.

        Args:
            namespace: The namespace.
            key: The setting key.
            value: The new value.
            skip_validation: If True, skip field validation.
            save: If True, persist to storage immediately (if auto-save enabled).

        Returns:
            Validation error message if invalid, None if successful.
        """
        # Validate if schema exists
        if not skip_validation:
            field = self.get_field(namespace, key)
            if field is not None:
                # 1. Schema-based validation
                error = field.validate(value)
                if error:
                    return error

            # 2. External validation
            validator_key = f"{namespace}:{key}"
            if validator_key in self._validators:
                try:
                    error = self._validators[validator_key](value)
                    if error:
                        return error
                except Exception as e:
                    logger.error(f"External validator failed for {namespace}.{key}: {e}")
                    return str(e)

        # Initialize namespace if needed
        if namespace not in self._values:
            self._values[namespace] = {}

        old_value = self._values[namespace].get(key)
        self._values[namespace][key] = value

        # Persist if auto-save enabled
        if self._auto_save and save:
            self._save_key(namespace, key, value)

        # Notify listeners if value changed
        if old_value != value:
            self._emit_change(namespace, key, value)

        return None

    def update(
        self,
        namespace: str,
        values: Dict[str, Any],
        skip_validation: bool = False,
    ) -> Dict[str, str]:
        """Update multiple settings at once.

        Args:
            namespace: The namespace.
            values: Dict of key-value pairs to update.
            skip_validation: If True, skip field validation.

        Returns:
            Dict of key -> error message for failed validations.
        """
        errors = {}
        changed = False

        for key, value in values.items():
            # Pass save=False to avoid writing to disk for each key
            error = self.set(namespace, key, value, skip_validation, save=False)
            if error:
                errors[key] = error
            else:
                changed = True

        # Save once if needed
        if self._auto_save and changed:
            self.save()

        return errors

    def reset_to_default(self, namespace: str, key: str) -> None:
        """Reset a setting to its default value.

        Args:
            namespace: The namespace.
            key: The setting key.
        """
        field = self.get_field(namespace, key)
        if field is not None:
            self.set(namespace, key, field.default)

    def reset_namespace(self, namespace: str) -> None:
        """Reset all settings in a namespace to defaults.

        Args:
            namespace: The namespace to reset.
        """
        if namespace not in self._namespaces:
            return

        for field in self._namespaces[namespace].schema:
            self.set(namespace, field.key, field.default)

    # ─────────────────────────────────────────────────────────────────
    # Schema Access (for UI)
    # ─────────────────────────────────────────────────────────────────

    def get_namespaces(self) -> List[RegisteredNamespace]:
        """Get all registered namespaces, sorted by order.

        Returns:
            List of RegisteredNamespace sorted by order.
        """
        return sorted(self._namespaces.values(), key=lambda ns: (ns.order, ns.name))

    def get_namespace(self, namespace: str) -> Optional[RegisteredNamespace]:
        """Get a specific registered namespace.

        Args:
            namespace: The namespace name.

        Returns:
            The RegisteredNamespace or None.
        """
        return self._namespaces.get(namespace)

    def get_schema(self, namespace: str) -> List[SettingField]:
        """Get the schema for a namespace.

        Args:
            namespace: The namespace.

        Returns:
            List of SettingField definitions.

        Raises:
            KeyError: If namespace not registered.
        """
        if namespace not in self._namespaces:
            raise KeyError(f"Namespace '{namespace}' not registered")
        return self._namespaces[namespace].schema

    def get_field(self, namespace: str, key: str) -> Optional[SettingField]:
        """Get a specific field definition.

        Args:
            namespace: The namespace.
            key: The field key.

        Returns:
            The SettingField or None.
        """
        if namespace not in self._namespaces:
            return None
        for field in self._namespaces[namespace].schema:
            if field.key == key:
                return field
        return None

    def is_secret(self, namespace: str, key: str) -> bool:
        """Check if a field is marked as secret.

        Args:
            namespace: The namespace.
            key: The field key.

        Returns:
            True if field has secret=True.
        """
        field = self.get_field(namespace, key)
        return field.secret if field else False

    def _get_env_key(self, namespace: str, key: str) -> str:
        """Get the environment variable key for a secret field.

        Uses field.env_key if specified, otherwise generates from namespace.

        Args:
            namespace: The namespace.
            key: The field key.

        Returns:
            Environment variable name.
        """
        field = self.get_field(namespace, key)
        if field and field.env_key:
            return field.env_key
        return namespace_to_env_key(namespace, key)

    # ─────────────────────────────────────────────────────────────────
    # Dynamic Options
    # ─────────────────────────────────────────────────────────────────

    def register_options_provider(
        self,
        name: str,
        provider: Callable[[], List[str]],
    ) -> None:
        """Register a callback for dynamic options.

        Args:
            name: Provider name (matches SettingField.options_provider).
            provider: Callable returning list of options.
        """
        self._options_providers[name] = provider

    def get_options(self, provider_name: str) -> List[str]:
        """Get options from a registered provider.

        Args:
            provider_name: The provider name.

        Returns:
            List of options or empty list if provider not found.
        """
        provider = self._options_providers.get(provider_name)
        if provider:
            try:
                return provider()
            except Exception as e:
                logger.warning(f"Options provider '{provider_name}' failed: {e}")
                return []
        return []

    # ─────────────────────────────────────────────────────────────────
    # Actions
    # ─────────────────────────────────────────────────────────────────

    def register_action_handler(
        self,
        namespace: str,
        action: str,
        handler: Callable[[], Any],
    ) -> None:
        """Register an action handler.

        Args:
            namespace: The namespace this action belongs to.
            action: The action name (matches SettingField.action).
            handler: Callable to execute the action.
        """
        key = f"{namespace}:{action}"
        self._action_handlers[key] = handler

    def register_validator(
        self,
        namespace: str,
        key: str,
        validator: Callable[[Any], Optional[str]],
    ) -> None:
        """Register an external validator for a setting.

        Args:
            namespace: The namespace.
            key: The setting key.
            validator: Callback accepting value, returning error string or None.
        """
        k = f"{namespace}:{key}"
        self._validators[k] = validator

    async def execute_action(
        self,
        namespace: str,
        action: str,
    ) -> ActionResult:
        """Execute a settings action.

        Args:
            namespace: The namespace.
            action: The action name (from SettingField.action).

        Returns:
            ActionResult with instructions for UI.
        """
        key = f"{namespace}:{action}"
        handler = self._action_handlers.get(key)

        if not handler:
            return ActionResult(
                type="error",
                message=f"No handler registered for action '{action}'",
            )

        try:
            result = handler()
            # If handler is async, await it
            import inspect
            if inspect.isawaitable(result):
                result = await result

            if isinstance(result, ActionResult):
                return result

            return ActionResult(type="success", message=str(result) if result else "")

        except Exception as e:
            logger.exception(f"Action '{action}' failed")
            return ActionResult(type="error", message=str(e))

    # ─────────────────────────────────────────────────────────────────
    # Events
    # ─────────────────────────────────────────────────────────────────

    def on_change(self, callback: Callable[[str, str, Any], None]) -> None:
        """Register a callback for setting changes.

        Args:
            callback: Function(namespace, key, value) called on changes.
        """
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[str, str, Any], None]) -> None:
        """Remove a change listener.

        Args:
            callback: The callback to remove.
        """
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _emit_change(self, namespace: str, key: str, value: Any) -> None:
        """Notify all listeners of a change.

        Args:
            namespace: The namespace that changed.
            key: The key that changed.
            value: The new value.
        """
        for listener in self._listeners:
            try:
                listener(namespace, key, value)
            except Exception as e:
                logger.warning(f"Settings listener error: {e}")

    # ─────────────────────────────────────────────────────────────────
    # Persistence
    # ─────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load values from YAML storage."""
        # Load YAML values
        yaml_data = self._yaml_storage.load()
        for namespace, ns_values in yaml_data.items():
            if isinstance(ns_values, dict):
                self._values[namespace] = ns_values

        logger.debug(f"Loaded settings from {self._config_dir}")

    def _save_key(self, namespace: str, key: str, value: Any) -> None:
        """Save a single key to appropriate storage.

        Args:
            namespace: The namespace.
            key: The setting key.
            value: The value to save.
        """
        if self.is_secret(namespace, key):
            env_key = self._get_env_key(namespace, key)
            self._env_storage.set(env_key, value)
        else:
            self._yaml_storage.set(namespace, key, value)

    def save(self) -> None:
        """Persist all values to storage.

        Useful when auto_save=False.
        """
        # Separate secrets from regular values
        yaml_values: Dict[str, Dict[str, Any]] = {}
        env_values: Dict[str, str] = {}

        for namespace, ns_values in self._values.items():
            yaml_values[namespace] = {}
            for key, value in ns_values.items():
                if self.is_secret(namespace, key):
                    env_key = self._get_env_key(namespace, key)
                    env_values[env_key] = str(value) if value else ""
                else:
                    yaml_values[namespace][key] = value

        self._yaml_storage.save(yaml_values)
        self._env_storage.save(env_values)

        logger.debug(f"Saved settings to {self._config_dir}")

    def reload(self) -> None:
        """Reload settings from storage, discarding unsaved changes."""
        self._values.clear()
        self._load()

        # Re-apply defaults for registered namespaces
        for ns in self._namespaces.values():
            if ns.name not in self._values:
                self._values[ns.name] = {}
            for field in ns.schema:
                if field.key not in self._values[ns.name]:
                    self._values[ns.name][field.key] = field.default

        logger.debug("Reloaded settings from storage")


# Global instance for singleton pattern (optional)
_global_settings: Optional[SettingsManager] = None


def get_settings_manager() -> Optional[SettingsManager]:
    """Get the global settings manager instance.

    Returns:
        The global SettingsManager or None if not initialized.
    """
    return _global_settings


def init_settings_manager(config_dir: Path, **kwargs) -> SettingsManager:
    """Initialize the global settings manager.

    Args:
        config_dir: Directory containing settings files.
        **kwargs: Additional arguments for SettingsManager.

    Returns:
        The initialized SettingsManager.
    """
    global _global_settings
    _global_settings = SettingsManager(config_dir, **kwargs)
    return _global_settings
