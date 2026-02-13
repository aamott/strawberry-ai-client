"""TensorZero TOML config generator.

Generates ``config/tensorzero.generated.toml`` from SettingsManager values
so users can configure LLM providers and fallback order through the settings
UI instead of hand-editing TOML.

See ``docs/plans/tensorzero-settings.md`` for design details.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from ..shared.settings import SettingsManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider descriptors — one per supported LLM backend
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ProviderDescriptor:
    """Describes how to generate TOML sections for one LLM provider.

    Attributes:
        id: Short identifier used in fallback_order list (e.g. "google").
        model_section: TOML ``[models.<name>]`` key.
        provider_name: TOML ``[models.<model>.providers.<name>]`` key.
        tz_type: TensorZero provider type string.
        variant_name: Variant name in ``[functions.*.variants.<name>]``.
        default_model: Default model name if not overridden by settings.
        api_key_env: Env var name for the API key, or "none".
        retries: Number of retries before falling back.
        max_delay_s: Max delay between retries in seconds.
        timeout_ms: Optional non-streaming timeout in milliseconds.
    """

    id: str
    model_section: str
    provider_name: str
    tz_type: str
    variant_name: str
    default_model: str = ""
    api_key_env: str = "none"
    retries: int = 1
    max_delay_s: int = 2
    timeout_ms: Optional[int] = None


# Registry of known providers
PROVIDER_REGISTRY: Dict[str, _ProviderDescriptor] = {}


def _register(*descriptors: _ProviderDescriptor) -> None:
    for d in descriptors:
        PROVIDER_REGISTRY[d.id] = d


_register(
    _ProviderDescriptor(
        id="hub",
        model_section="hub_gateway",
        provider_name="hub",
        tz_type="openai",
        variant_name="hub",
        default_model="strawberry-chat",
        api_key_env="HUB_DEVICE_TOKEN",
        retries=0,
        max_delay_s=2,
        timeout_ms=800,
    ),
    _ProviderDescriptor(
        id="google",
        model_section="google_gemini",
        provider_name="google",
        tz_type="google_ai_studio_gemini",
        variant_name="google_variant",
        default_model="gemini-2.5-flash-lite",
        api_key_env="GOOGLE_AI_STUDIO_API_KEY",
    ),
    _ProviderDescriptor(
        id="openai",
        model_section="openai_model",
        provider_name="openai",
        tz_type="openai",
        variant_name="openai_variant",
        default_model="gpt-4o-mini",
        api_key_env="OPENAI_API_KEY",
    ),
    _ProviderDescriptor(
        id="anthropic",
        model_section="anthropic_model",
        provider_name="anthropic",
        tz_type="anthropic",
        variant_name="anthropic_variant",
        default_model="claude-sonnet-4-20250514",
        api_key_env="ANTHROPIC_API_KEY",
    ),
    _ProviderDescriptor(
        id="ollama",
        model_section="ollama_local",
        provider_name="ollama",
        tz_type="openai",
        variant_name="local_ollama",
        default_model="llama3.2:3b",
        api_key_env="none",
    ),
    _ProviderDescriptor(
        id="custom",
        model_section="custom_model",
        provider_name="custom",
        tz_type="openai",
        variant_name="custom_variant",
        default_model="",
        api_key_env="CUSTOM_LLM_API_KEY",
    ),
)

# Provider IDs available for the fallback_order LIST field
PROVIDER_IDS: List[str] = list(PROVIDER_REGISTRY.keys())

# Default fallback order
DEFAULT_FALLBACK_ORDER: List[str] = ["hub", "google", "ollama"]


# ---------------------------------------------------------------------------
# Resolve provider settings from SettingsManager
# ---------------------------------------------------------------------------


@dataclass
class _ResolvedProvider:
    """A provider with all settings resolved, ready for TOML generation."""

    descriptor: _ProviderDescriptor
    model_name: str = ""
    api_base: Optional[str] = None
    enabled: bool = False


def _resolve_providers(
    settings: "SettingsManager",
    fallback_order: List[str],
) -> List[_ResolvedProvider]:
    """Resolve provider settings into an ordered list for TOML generation.

    Args:
        settings: The SettingsManager to read from.
        fallback_order: Ordered list of provider IDs.

    Returns:
        Ordered list of resolved, enabled providers.
    """
    resolved: List[_ResolvedProvider] = []

    for pid in fallback_order:
        desc = PROVIDER_REGISTRY.get(pid)
        if desc is None:
            logger.warning("Unknown provider ID in fallback_order: %s", pid)
            continue

        prov = _ResolvedProvider(descriptor=desc)

        if pid == "hub":
            # Hub config comes from spoke_core namespace
            hub_url = settings.get("spoke_core", "hub.url", "http://localhost:8000")
            prov.api_base = f"{hub_url}/api/v1"
            prov.model_name = desc.default_model
            # Hub is enabled if token exists (even dummy is fine — TZ handles 401)
            prov.enabled = True

        elif pid == "ollama":
            # Ollama config comes from tensorzero namespace
            prov.api_base = settings.get(
                "tensorzero", "ollama.url", "http://localhost:11434/v1"
            )
            prov.model_name = settings.get(
                "tensorzero", "ollama.model", desc.default_model
            )
            prov.enabled = True  # Always available as local safety net

        elif pid == "custom":
            # Custom provider from tensorzero namespace
            prov.model_name = settings.get(
                "tensorzero", "custom.model", ""
            )
            prov.api_base = settings.get(
                "tensorzero", "custom.api_base", ""
            )
            api_key = os.environ.get(desc.api_key_env, "")
            # Enabled only if model, api_base, and api_key are all set
            prov.enabled = bool(
                prov.model_name and prov.api_base and api_key
            )

        else:
            # Cloud providers (google, openai, anthropic) from tensorzero namespace
            prov.model_name = settings.get(
                "tensorzero", f"{pid}.model", desc.default_model
            )
            # Enabled if API key env var is set
            api_key = os.environ.get(desc.api_key_env, "")
            prov.enabled = bool(api_key)

        if prov.enabled:
            resolved.append(prov)
        else:
            logger.debug(
                "Provider '%s' skipped (disabled or missing API key)", pid
            )

    return resolved


# ---------------------------------------------------------------------------
# TOML generation
# ---------------------------------------------------------------------------

_GATEWAY_HEADER = """\
# =============================================================================
# Auto-generated TensorZero Configuration
# Generated from SettingsManager — do not edit manually.
# Edit via: strawberry-cli --settings, /settings, or the GUI settings panel.
# =============================================================================

[gateway]
observability.enabled = false
"""

_TOOLS_SECTION = """\

# -----------------------------------------------------------------------------
# Tools (static)
# -----------------------------------------------------------------------------

[tools.search_skills]
description = "Search for available skills by keyword."
parameters = "tools/search_skills.json"

[tools.describe_function]
description = "Get full function signature for a skill method."
parameters = "tools/describe_function.json"

[tools.python_exec]
description = "Execute Python code in a sandbox."
parameters = "tools/python_exec.json"
"""


def _build_model_section(prov: _ResolvedProvider) -> str:
    """Build the TOML [models.*] section for one provider."""
    d = prov.descriptor
    lines = [
        f'[models.{d.model_section}]',
        f'routing = ["{d.provider_name}"]',
        "",
        f'[models.{d.model_section}.providers.{d.provider_name}]',
        f'type = "{d.tz_type}"',
        f'model_name = "{prov.model_name}"',
    ]

    if prov.api_base:
        lines.append(f'api_base = "{prov.api_base}"')

    if d.api_key_env == "none":
        lines.append('api_key_location = "none"')
    else:
        lines.append(f'api_key_location = "env::{d.api_key_env}"')

    if d.timeout_ms:
        lines.append(f'[models.{d.model_section}.providers.{d.provider_name}.timeouts]')
        lines.append(f'non_streaming = {{ total_ms = {d.timeout_ms} }}')

    return "\n".join(lines)


def _build_variant_section(
    func_name: str,
    prov: _ResolvedProvider,
) -> str:
    """Build the variant section for one provider within a function."""
    d = prov.descriptor
    lines = [
        f'[functions.{func_name}.variants.{d.variant_name}]',
        'type = "chat_completion"',
        f'model = "{d.model_section}"',
        f'[functions.{func_name}.variants.{d.variant_name}.retries]',
        f'num_retries = {d.retries}',
        f'max_delay_s = {d.max_delay_s}',
    ]
    return "\n".join(lines)


def _build_function_section(
    func_name: str,
    providers: List[_ResolvedProvider],
) -> str:
    """Build a complete [functions.*] section with experimentation + variants.

    Args:
        func_name: Function name (e.g. "chat" or "chat_local").
        providers: Ordered list of enabled providers for this function.

    Returns:
        TOML string for the function section.
    """
    if not providers:
        return ""

    # First provider is the candidate; rest are fallbacks
    candidate = providers[0]
    fallbacks = providers[1:]

    candidate_list = f'["{candidate.descriptor.variant_name}"]'
    fallback_list = ", ".join(
        f'"{p.descriptor.variant_name}"' for p in fallbacks
    )

    lines = [
        f"[functions.{func_name}]",
        'type = "chat"',
        'tools = ["search_skills", "describe_function", "python_exec"]',
        "",
        f"[functions.{func_name}.experimentation]",
        'type = "uniform"',
        f"candidate_variants = {candidate_list}",
    ]
    if fallbacks:
        lines.append(f"fallback_variants = [{fallback_list}]")

    lines.append("")

    # Add variant sections
    for prov in providers:
        lines.append(_build_variant_section(func_name, prov))
        lines.append("")

    return "\n".join(lines)


def generate_toml(settings: "SettingsManager") -> str:
    """Generate the full TensorZero TOML config from settings.

    Args:
        settings: The SettingsManager to read provider config from.

    Returns:
        Complete TOML config string.
    """
    fallback_order = settings.get(
        "tensorzero", "fallback_order", DEFAULT_FALLBACK_ORDER
    )
    if not isinstance(fallback_order, list):
        fallback_order = list(DEFAULT_FALLBACK_ORDER)

    all_providers = _resolve_providers(settings, fallback_order)

    # Split into online (with hub) and offline (without hub) lists
    online_providers = all_providers
    offline_providers = [p for p in all_providers if p.descriptor.id != "hub"]

    # Collect unique providers across both functions
    seen_models = set()
    unique_providers: List[_ResolvedProvider] = []
    for prov in all_providers:
        if prov.descriptor.model_section not in seen_models:
            seen_models.add(prov.descriptor.model_section)
            unique_providers.append(prov)

    # Build TOML
    parts = [_GATEWAY_HEADER]

    # Model sections
    parts.append("\n# " + "-" * 77)
    parts.append("# Models")
    parts.append("# " + "-" * 77 + "\n")
    for prov in unique_providers:
        parts.append(_build_model_section(prov))
        parts.append("")

    # Tools
    parts.append(_TOOLS_SECTION)

    # Functions
    parts.append("# " + "-" * 77)
    parts.append("# Functions")
    parts.append("# " + "-" * 77 + "\n")

    # Online function (chat) — includes Hub
    if online_providers:
        parts.append("# Online: Hub primary, cloud + local fallbacks")
        parts.append(_build_function_section("chat", online_providers))

    # Offline function (chat_local) — excludes Hub
    if offline_providers:
        parts.append("# Offline: cloud + local only (no Hub)")
        parts.append(_build_function_section("chat_local", offline_providers))

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# File management
# ---------------------------------------------------------------------------


def get_generated_config_path() -> Path:
    """Get the path for the generated TOML file.

    Returns:
        Path to ``config/tensorzero.generated.toml``.
    """
    project_root = Path(__file__).parent.parent.parent.parent
    return project_root / "config" / "tensorzero.generated.toml"


def write_generated_config(settings: "SettingsManager") -> str:
    """Generate and write the TensorZero TOML config file.

    Args:
        settings: The SettingsManager to read provider config from.

    Returns:
        Absolute path to the written config file.
    """
    toml_content = generate_toml(settings)
    output_path = get_generated_config_path()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(toml_content, encoding="utf-8")

    logger.info("Wrote TensorZero config to %s", output_path)
    return str(output_path)
