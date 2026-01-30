"""View model for settings UI.

This module provides the SettingsViewModel class that presents settings
in a structured format suitable for UI rendering.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from .manager import SettingsManager
from .schema import FieldType, SettingField


@dataclass
class SettingsSection:
    """A section in the settings UI (corresponds to a namespace).

    Attributes:
        namespace: The namespace identifier.
        display_name: Human-readable name for UI.
        groups: Dictionary mapping group names to lists of fields.
        values: Current values for all fields.
        order: Display order (lower = first).
    """

    namespace: str
    display_name: str
    groups: Dict[str, List[SettingField]]
    values: Dict[str, Any]
    order: int


@dataclass
class ProviderSection:
    """A provider selection with its sub-settings.

    Used for STT/TTS/VAD/WakeWord provider selection where selecting
    a provider shows that provider's specific settings.

    Attributes:
        parent_namespace: The parent namespace (e.g., "voice_core").
        provider_field: The field that selects the provider.
        provider_key: The key for the provider selection (e.g., "stt.backend").
        available_providers: List of available provider names.
        selected_provider: Currently selected provider name.
        provider_settings_namespace: Namespace for selected provider's settings.
        provider_display_name: Human-readable name for the provider type.
    """

    parent_namespace: str
    provider_field: SettingField
    provider_key: str
    available_providers: List[str]
    selected_provider: str
    provider_settings_namespace: str
    provider_display_name: str = ""


@dataclass
class ValidationResult:
    """Result of validating a field value.

    Attributes:
        valid: Whether the value is valid.
        error: Error message if invalid.
        field_key: The field key that was validated.
    """

    valid: bool
    error: Optional[str] = None
    field_key: str = ""


class SettingsViewModel:
    """View model for settings UI.

    Provides a structured view of settings organized for UI rendering.
    Handles the logic of provider selection and sub-settings.

    Example:
        vm = SettingsViewModel(settings_manager)

        # Get sections for tabs/accordion
        sections = vm.get_sections()

        # Get provider sections (STT, TTS with their backends)
        providers = vm.get_provider_sections("voice_core")

        # Update a value
        vm.set_value("spoke_core", "hub.url", "https://...")

        # Listen for external changes
        vm.on_refresh(lambda: render_ui())
    """

    def __init__(self, settings_manager: SettingsManager):
        """Initialize the view model.

        Args:
            settings_manager: The SettingsManager to read/write settings.
        """
        self._settings = settings_manager
        self._refresh_callbacks: List[Callable[[], None]] = []

        # Listen for changes from other sources
        self._settings.on_change(self._on_external_change)

    @property
    def settings_manager(self) -> SettingsManager:
        """Get the underlying settings manager."""
        return self._settings

    # ─────────────────────────────────────────────────────────────────
    # Sections (for main tabs/accordion)
    # ─────────────────────────────────────────────────────────────────

    def get_sections(
        self, include_provider_children: bool = False
    ) -> List[SettingsSection]:
        """Get all settings sections for rendering.

        Args:
            include_provider_children: If False, excludes provider sub-namespaces
                                       (e.g., voice.stt.whisper) since they're
                                       rendered inline with their parent.

        Returns:
            List of SettingsSection sorted by order.
        """
        sections = []

        for ns in self._settings.get_namespaces():
            # Skip provider sub-namespaces unless requested
            if not include_provider_children and self._is_provider_namespace(ns.name):
                continue

            section = SettingsSection(
                namespace=ns.name,
                display_name=ns.display_name,
                groups=self._group_fields(ns.schema),
                values=self._settings.get_all(ns.name),
                order=ns.order,
            )
            sections.append(section)

        return sorted(sections, key=lambda s: (s.order, s.namespace))

    def get_section(self, namespace: str) -> Optional[SettingsSection]:
        """Get a single section by namespace.

        Args:
            namespace: The namespace identifier.

        Returns:
            The SettingsSection or None if not found.
        """
        ns = self._settings.get_namespace(namespace)
        if not ns:
            return None

        return SettingsSection(
            namespace=ns.name,
            display_name=ns.display_name,
            groups=self._group_fields(ns.schema),
            values=self._settings.get_all(ns.name),
            order=ns.order,
        )

    def _is_provider_namespace(self, namespace: str) -> bool:
        """Check if namespace is a provider sub-namespace.

        Provider namespaces look like: voice.stt.whisper, voice.tts.orca

        Args:
            namespace: The namespace to check.

        Returns:
            True if this is a provider sub-namespace.
        """
        parts = namespace.split(".")
        return len(parts) >= 3 and parts[0] == "voice"

    def _group_fields(
        self, schema: List[SettingField]
    ) -> Dict[str, List[SettingField]]:
        """Group fields by their group attribute.

        Args:
            schema: List of SettingField objects.

        Returns:
            Dictionary mapping group names to lists of fields.
        """
        groups: Dict[str, List[SettingField]] = {}
        for setting_field in schema:
            if setting_field.group not in groups:
                groups[setting_field.group] = []
            groups[setting_field.group].append(setting_field)
        return groups

    # ─────────────────────────────────────────────────────────────────
    # Provider Sections (STT/TTS with sub-settings)
    # ─────────────────────────────────────────────────────────────────

    def get_provider_sections(self, namespace: str) -> List[ProviderSection]:
        """Get provider selection sections for a namespace.

        This identifies fields that select a provider (e.g., stt.order)
        and pairs them with the selected provider's settings namespace.

        Args:
            namespace: The parent namespace (e.g., "voice_core").

        Returns:
            List of ProviderSection for each provider selector in the namespace.
        """
        sections = []

        try:
            schema = self._settings.get_schema(namespace)
        except KeyError:
            return sections

        values = self._settings.get_all(namespace)

        # Find provider selection patterns
        for pattern in self._find_provider_patterns(namespace, schema, values):
            sections.append(pattern)

        return sections

    def _find_provider_patterns(
        self,
        namespace: str,
        schema: List[SettingField],
        values: Dict[str, Any],
    ) -> List[ProviderSection]:
        """Find fields that select providers with sub-settings.

        Args:
            namespace: The parent namespace.
            schema: The schema for the namespace.
            values: Current values for the namespace.

        Returns:
            List of ProviderSection objects.
        """
        patterns = []

        for setting_field in schema:
            # Check for explicit PROVIDER_SELECT type
            if setting_field.type == FieldType.PROVIDER_SELECT:
                if not setting_field.provider_type:
                    continue

                provider_type = setting_field.provider_type

                # Determine currently selected provider
                # Logic handles both "order" (comma-separated list) and simple selection
                raw_value = values.get(setting_field.key, setting_field.default) or ""

                # If value is a list (like "order"), take the first one
                if "," in str(raw_value):
                    parts = [p.strip() for p in str(raw_value).split(",") if p.strip()]
                    selected = parts[0] if parts else ""
                else:
                    selected = str(raw_value)

                available = self._get_available_providers(provider_type)

                # Determine provider namespace using template or fallback
                if setting_field.provider_namespace_template:
                    provider_ns = setting_field.provider_namespace_template.format(
                        provider_type=provider_type,
                        value=selected
                    )
                else:
                    # Default/Fallback behavior (backward compatibility)
                    provider_ns = f"voice.{provider_type}.{selected}"

                display_name = provider_type.upper()

                patterns.append(
                    ProviderSection(
                        parent_namespace=namespace,
                        provider_field=setting_field,
                        provider_key=setting_field.key,
                        available_providers=available,
                        selected_provider=selected,
                        provider_settings_namespace=provider_ns,
                        provider_display_name=display_name,
                    )
                )
                continue

            # FALLBACK: Keep backward compatibility with existing implicit patterns for now
            # (or remove if we decide to fully migrate immediately, but safer to keep)
            if setting_field.key.endswith(".order"):
                # Extract provider type (e.g., "stt" from "stt.order")
                provider_type = setting_field.key.rsplit(".", 1)[0]

                # Get the order value and extract first provider
                order_value = values.get(setting_field.key, setting_field.default) or ""
                providers = [p.strip() for p in str(order_value).split(",") if p.strip()]

                if not providers:
                    continue

                # Find available providers by checking registered namespaces
                available = self._get_available_providers(provider_type)

                # The "selected" provider is the first in the order
                selected = providers[0] if providers else ""
                provider_ns = f"voice.{provider_type}.{selected}"
                display_name = provider_type.upper()

                patterns.append(
                    ProviderSection(
                        parent_namespace=namespace,
                        provider_field=setting_field,
                        provider_key=setting_field.key,
                        available_providers=available,
                        selected_provider=selected,
                        provider_settings_namespace=provider_ns,
                        provider_display_name=display_name,
                    )
                )

            elif setting_field.key.endswith(".backend"):
                provider_type = setting_field.key.rsplit(".", 1)[0]
                selected = values.get(setting_field.key, setting_field.default) or ""
                available = self._get_available_providers(provider_type)
                provider_ns = f"voice.{provider_type}.{selected}"

                display_name = provider_type.upper()

                patterns.append(
                    ProviderSection(
                        parent_namespace=namespace,
                        provider_field=setting_field,
                        provider_key=setting_field.key,
                        available_providers=available,
                        selected_provider=str(selected),
                        provider_settings_namespace=provider_ns,
                        provider_display_name=display_name,
                    )
                )

        return patterns

    def _get_available_providers(self, provider_type: str) -> List[str]:
        """Get available providers for a type (stt, tts, etc.).

        Args:
            provider_type: The provider type (e.g., "stt", "tts").

        Returns:
            List of available provider names.
        """
        providers = []
        prefix = f"voice.{provider_type}."

        for ns in self._settings.get_namespaces():
            if ns.name.startswith(prefix):
                provider_name = ns.name[len(prefix) :]
                providers.append(provider_name)

        return sorted(providers)

    def get_provider_settings(
        self, provider_type: str, provider_name: str
    ) -> Optional[SettingsSection]:
        """Get the settings section for a specific provider.

        Args:
            provider_type: "stt", "tts", "vad", "wakeword".
            provider_name: "whisper", "leopard", "orca", etc.

        Returns:
            SettingsSection for the provider or None.
        """
        namespace = f"voice.{provider_type}.{provider_name}"
        return self.get_section(namespace)

    # ─────────────────────────────────────────────────────────────────
    # Values
    # ─────────────────────────────────────────────────────────────────

    def get_value(self, namespace: str, key: str, default: Any = None) -> Any:
        """Get a setting value.

        Args:
            namespace: The namespace.
            key: The setting key.
            default: Default value if not set.

        Returns:
            The setting value.
        """
        return self._settings.get(namespace, key, default)

    def set_value(self, namespace: str, key: str, value: Any) -> Optional[str]:
        """Set a setting value.

        Args:
            namespace: The namespace.
            key: The setting key.
            value: The new value.

        Returns:
            Error message if validation failed, None if successful.
        """
        return self._settings.set(namespace, key, value)

    def get_options(self, provider_name: str) -> List[str]:
        """Get dynamic options for a DYNAMIC_SELECT field.

        Args:
            provider_name: The options provider name.

        Returns:
            List of available options.
        """
        return self._settings.get_options(provider_name)

    # ─────────────────────────────────────────────────────────────────
    # Validation
    # ─────────────────────────────────────────────────────────────────

    def validate_field(
        self, namespace: str, key: str, value: Any
    ) -> ValidationResult:
        """Validate a field value.

        Args:
            namespace: The namespace.
            key: The field key.
            value: The value to validate.

        Returns:
            ValidationResult with validity and error message.
        """
        setting_field = self._settings.get_field(namespace, key)
        if not setting_field:
            return ValidationResult(valid=True, field_key=key)

        error = setting_field.validate(value)
        return ValidationResult(
            valid=error is None,
            error=error,
            field_key=key,
        )

    def validate_section(
        self, namespace: str, values: Dict[str, Any]
    ) -> List[ValidationResult]:
        """Validate all fields in a section.

        Args:
            namespace: The namespace.
            values: Dictionary of key -> value to validate.

        Returns:
            List of ValidationResult for each invalid field.
        """
        results = []
        for key, value in values.items():
            result = self.validate_field(namespace, key, value)
            if not result.valid:
                results.append(result)
        return results

    # ─────────────────────────────────────────────────────────────────
    # Provider Management
    # ─────────────────────────────────────────────────────────────────

    def set_primary_provider(
        self,
        namespace: str,
        provider_key: str,
        provider_name: str,
    ) -> None:
        """Set a provider as the primary (first in order).

        Args:
            namespace: The parent namespace (e.g., "voice_core").
            provider_key: The key for the provider order (e.g., "stt.order").
            provider_name: The provider to make primary.
        """
        current_order = self.get_value(namespace, provider_key) or ""
        providers = [p.strip() for p in str(current_order).split(",") if p.strip()]

        # Remove provider from current position
        if provider_name in providers:
            providers.remove(provider_name)

        # Insert at front
        providers.insert(0, provider_name)

        new_order = ",".join(providers)
        self.set_value(namespace, provider_key, new_order)

    def get_provider_order(self, namespace: str, provider_key: str) -> List[str]:
        """Get the current provider order.

        Args:
            namespace: The parent namespace.
            provider_key: The key for the provider order.

        Returns:
            List of provider names in order.
        """
        order_value = self.get_value(namespace, provider_key) or ""
        return [p.strip() for p in str(order_value).split(",") if p.strip()]

    # ─────────────────────────────────────────────────────────────────
    # Events
    # ─────────────────────────────────────────────────────────────────

    def on_refresh(self, callback: Callable[[], None]) -> None:
        """Register callback for when UI should refresh.

        Args:
            callback: Function to call when settings change externally.
        """
        self._refresh_callbacks.append(callback)

    def remove_refresh_callback(self, callback: Callable[[], None]) -> None:
        """Remove a refresh callback.

        Args:
            callback: The callback to remove.
        """
        if callback in self._refresh_callbacks:
            self._refresh_callbacks.remove(callback)

    def _on_external_change(self, namespace: str, key: str, value: Any) -> None:
        """Handle changes from outside the UI.

        Args:
            namespace: The namespace that changed.
            key: The key that changed.
            value: The new value.
        """
        for callback in self._refresh_callbacks:
            try:
                callback()
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────
    # Utility Methods
    # ─────────────────────────────────────────────────────────────────

    def get_field_display_value(
        self, namespace: str, key: str, mask_secrets: bool = True
    ) -> str:
        """Get a display-friendly value for a field.

        Args:
            namespace: The namespace.
            key: The field key.
            mask_secrets: If True, mask secret values with "••••••••".

        Returns:
            Display-friendly string value.
        """
        value = self.get_value(namespace, key)
        setting_field = self._settings.get_field(namespace, key)

        if setting_field and setting_field.secret and mask_secrets and value:
            return "••••••••"

        if value is None:
            return ""

        return str(value)

    def is_field_empty(self, namespace: str, key: str) -> bool:
        """Check if a field has no value set.

        Args:
            namespace: The namespace.
            key: The field key.

        Returns:
            True if the field has no value (None or empty string).
        """
        value = self.get_value(namespace, key)
        return value is None or value == ""

    def get_empty_required_fields(self, namespace: str) -> List[SettingField]:
        """Get list of required fields that are empty.

        Note: Currently identifies PASSWORD fields without values as
        "required" since they're typically API keys needed for functionality.

        Args:
            namespace: The namespace to check.

        Returns:
            List of SettingField objects that are empty but likely required.
        """
        empty_fields = []

        try:
            schema = self._settings.get_schema(namespace)
        except KeyError:
            return empty_fields

        for setting_field in schema:
            # Consider PASSWORD fields without values as requiring attention
            if setting_field.type == FieldType.PASSWORD:
                if self.is_field_empty(namespace, setting_field.key):
                    empty_fields.append(setting_field)

        return empty_fields
