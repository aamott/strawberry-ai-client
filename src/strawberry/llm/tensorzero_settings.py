"""TensorZero provider settings schema.

Defines the ``tensorzero`` namespace for SettingsManager, covering
cloud LLM provider configuration and fallback ordering.

Hub and Ollama settings live in the ``spoke_core`` namespace (hub.url,
hub.token, local_llm.url, local_llm.model) — they are NOT duplicated here.
"""

from typing import TYPE_CHECKING, List

from ..shared.settings import FieldType, SettingField
from .tensorzero_config import DEFAULT_FALLBACK_ORDER, PROVIDER_IDS

if TYPE_CHECKING:
    from ..shared.settings import SettingsManager

# Schema version for the tensorzero namespace
SCHEMA_VERSION = 1

TENSORZERO_SCHEMA: List[SettingField] = [
    # ── Fallback Order ──────────────────────────────────────────────
    SettingField(
        key="fallback_order",
        label="LLM Fallback Order",
        type=FieldType.PROVIDER_SELECT,
        default=DEFAULT_FALLBACK_ORDER,
        description="Priority order for LLM providers (first = primary)",
        group="fallback",
        options=PROVIDER_IDS,
        allow_custom=False,
        metadata={
            "help_text": (
                "Reorder to set LLM priority.\n"
                "The first provider is tried first; if it fails,\n"
                "the next one is tried, and so on.\n\n"
                "Providers without a valid API key are skipped\n"
                "automatically.\n\n"
                "Available: hub, google, openai, anthropic,\n"
                "ollama, custom"
            )
        },
    ),
    # ── Google AI Studio ────────────────────────────────────────────
    SettingField(
        key="google.api_key",
        label="Google AI Studio API Key",
        type=FieldType.PASSWORD,
        secret=True,
        description="API key for Google AI Studio (Gemini models)",
        group="google",
        env_key="GOOGLE_AI_STUDIO_API_KEY",
        metadata={
            "help_text": (
                "Get a key at https://aistudio.google.com/apikey\n"
                "Leave empty to disable Google as a fallback."
            )
        },
    ),
    SettingField(
        key="google.model",
        label="Google Model",
        type=FieldType.TEXT,
        default="gemini-2.5-flash-lite",
        description="Google AI Studio model name",
        group="google",
        metadata={
            "help_text": (
                "Model identifier for Google AI Studio.\n"
                "Examples: gemini-2.5-flash-lite, gemini-2.5-pro"
            )
        },
    ),
    # ── OpenAI ──────────────────────────────────────────────────────
    SettingField(
        key="openai.api_key",
        label="OpenAI API Key",
        type=FieldType.PASSWORD,
        secret=True,
        description="API key for OpenAI",
        group="openai",
        env_key="OPENAI_API_KEY",
        metadata={
            "help_text": (
                "Get a key at https://platform.openai.com/api-keys\n"
                "Leave empty to disable OpenAI as a fallback."
            )
        },
    ),
    SettingField(
        key="openai.model",
        label="OpenAI Model",
        type=FieldType.TEXT,
        default="gpt-4o-mini",
        description="OpenAI model name",
        group="openai",
        metadata={
            "help_text": (
                "Model identifier for OpenAI.\n"
                "Examples: gpt-4o-mini, gpt-4o, o3-mini"
            )
        },
    ),
    # ── Anthropic ───────────────────────────────────────────────────
    SettingField(
        key="anthropic.api_key",
        label="Anthropic API Key",
        type=FieldType.PASSWORD,
        secret=True,
        description="API key for Anthropic (Claude models)",
        group="anthropic",
        env_key="ANTHROPIC_API_KEY",
        metadata={
            "help_text": (
                "Get a key at https://console.anthropic.com/\n"
                "Leave empty to disable Anthropic as a fallback."
            )
        },
    ),
    SettingField(
        key="anthropic.model",
        label="Anthropic Model",
        type=FieldType.TEXT,
        default="claude-sonnet-4-20250514",
        description="Anthropic model name",
        group="anthropic",
        metadata={
            "help_text": (
                "Model identifier for Anthropic.\n"
                "Examples: claude-sonnet-4-20250514,\n"
                "claude-haiku-3-5-20241022"
            )
        },
    ),
    # ── Custom OpenAI-Compatible ────────────────────────────────────
    SettingField(
        key="custom.label",
        label="Custom Provider Name",
        type=FieldType.TEXT,
        default="",
        description="Display name for the custom provider",
        group="custom",
        placeholder="e.g. Together AI, Groq, LM Studio",
    ),
    SettingField(
        key="custom.api_key",
        label="Custom API Key",
        type=FieldType.PASSWORD,
        secret=True,
        description="API key for the custom provider",
        group="custom",
        env_key="CUSTOM_LLM_API_KEY",
    ),
    SettingField(
        key="custom.api_base",
        label="Custom API Base URL",
        type=FieldType.TEXT,
        default="",
        description="Base URL for the OpenAI-compatible API",
        group="custom",
        placeholder="e.g. https://api.together.xyz/v1",
        metadata={
            "help_text": (
                "Any OpenAI-compatible endpoint works here.\n"
                "Examples:\n"
                "  Together: https://api.together.xyz/v1\n"
                "  Groq: https://api.groq.com/openai/v1\n"
                "  LM Studio: http://localhost:1234/v1"
            )
        },
    ),
    SettingField(
        key="custom.model",
        label="Custom Model Name",
        type=FieldType.TEXT,
        default="",
        description="Model name for the custom provider",
        group="custom",
        placeholder="e.g. meta-llama/Llama-3-70b-chat-hf",
    ),
]


def register_tensorzero_schema(settings: "SettingsManager") -> None:
    """Register the tensorzero namespace with SettingsManager.

    Args:
        settings: The SettingsManager instance.
    """
    if settings.is_registered("tensorzero"):
        return

    settings.register(
        namespace="tensorzero",
        display_name="LLM Providers",
        schema=TENSORZERO_SCHEMA,
        order=15,  # Between Spoke Core (10) and Skills (50+)
        tab="General",
        schema_version=SCHEMA_VERSION,
    )
