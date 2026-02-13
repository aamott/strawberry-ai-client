"""Tests for TensorZero TOML config generation from settings."""

import os
from pathlib import Path

import pytest

from strawberry.llm.tensorzero_config import (
    DEFAULT_FALLBACK_ORDER,
    PROVIDER_IDS,
    PROVIDER_REGISTRY,
    _resolve_providers,
    generate_toml,
)
from strawberry.llm.tensorzero_settings import (
    TENSORZERO_SCHEMA,
    register_tensorzero_schema,
)
from strawberry.shared.settings import SettingsManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def settings(tmp_path: Path) -> SettingsManager:
    """Create a SettingsManager with spoke_core + tensorzero registered."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    sm = SettingsManager(config_dir=config_dir, auto_save=False)

    # Register spoke_core with minimal schema (hub + ollama settings)
    from strawberry.spoke_core.settings_schema import register_spoke_core_schema

    register_spoke_core_schema(sm)

    # Register tensorzero schema
    register_tensorzero_schema(sm)

    return sm


# ---------------------------------------------------------------------------
# Provider Registry
# ---------------------------------------------------------------------------


class TestProviderRegistry:
    """Tests for the provider descriptor registry."""

    def test_all_default_providers_registered(self):
        """All 6 expected providers should be in the registry."""
        expected = {"hub", "google", "openai", "anthropic", "ollama", "custom"}
        assert set(PROVIDER_REGISTRY.keys()) == expected

    def test_provider_ids_matches_registry(self):
        """PROVIDER_IDS list should match registry keys."""
        assert set(PROVIDER_IDS) == set(PROVIDER_REGISTRY.keys())

    def test_default_fallback_order_valid(self):
        """Default fallback order should only contain valid provider IDs."""
        for pid in DEFAULT_FALLBACK_ORDER:
            assert pid in PROVIDER_REGISTRY

    def test_hub_has_short_timeout(self):
        """Hub should fail fast (short timeout) to enable quick fallback."""
        hub = PROVIDER_REGISTRY["hub"]
        assert hub.timeout_ms is not None
        assert hub.timeout_ms <= 1000

    def test_hub_has_zero_retries(self):
        """Hub should not retry — fail fast to fallback."""
        hub = PROVIDER_REGISTRY["hub"]
        assert hub.retries == 0


# ---------------------------------------------------------------------------
# Provider Resolution
# ---------------------------------------------------------------------------


class TestProviderResolution:
    """Tests for resolving settings into provider configs."""

    def test_hub_always_enabled(self, settings: SettingsManager):
        """Hub should always be resolved as enabled."""
        resolved = _resolve_providers(settings, ["hub"])
        assert len(resolved) == 1
        assert resolved[0].descriptor.id == "hub"
        assert resolved[0].enabled

    def test_ollama_always_enabled(self, settings: SettingsManager):
        """Ollama should always be resolved as enabled."""
        resolved = _resolve_providers(settings, ["ollama"])
        assert len(resolved) == 1
        assert resolved[0].descriptor.id == "ollama"
        assert resolved[0].enabled

    def test_google_disabled_without_key(self, settings: SettingsManager):
        """Google should be disabled when API key is not set."""
        # Ensure no API key
        os.environ.pop("GOOGLE_AI_STUDIO_API_KEY", None)
        resolved = _resolve_providers(settings, ["google"])
        assert len(resolved) == 0

    def test_google_enabled_with_key(
        self, settings: SettingsManager, monkeypatch: pytest.MonkeyPatch,
    ):
        """Google should be enabled when API key is set."""
        monkeypatch.setenv("GOOGLE_AI_STUDIO_API_KEY", "test-key")
        resolved = _resolve_providers(settings, ["google"])
        assert len(resolved) == 1
        assert resolved[0].descriptor.id == "google"

    def test_openai_disabled_without_key(self, settings: SettingsManager):
        """OpenAI should be disabled when API key is not set."""
        os.environ.pop("OPENAI_API_KEY", None)
        resolved = _resolve_providers(settings, ["openai"])
        assert len(resolved) == 0

    def test_custom_disabled_without_full_config(
        self, settings: SettingsManager,
    ):
        """Custom provider needs model, api_base, and api_key."""
        os.environ.pop("CUSTOM_LLM_API_KEY", None)
        resolved = _resolve_providers(settings, ["custom"])
        assert len(resolved) == 0

    def test_custom_enabled_with_full_config(
        self, settings: SettingsManager, monkeypatch: pytest.MonkeyPatch,
    ):
        """Custom provider should enable when all fields are set."""
        monkeypatch.setenv("CUSTOM_LLM_API_KEY", "test-key")
        settings.set("tensorzero", "custom.model", "my-model")
        settings.set("tensorzero", "custom.api_base", "http://localhost:1234/v1")
        resolved = _resolve_providers(settings, ["custom"])
        assert len(resolved) == 1
        assert resolved[0].descriptor.id == "custom"

    def test_order_preserved(
        self, settings: SettingsManager, monkeypatch: pytest.MonkeyPatch,
    ):
        """Resolved providers should preserve fallback_order."""
        monkeypatch.setenv("GOOGLE_AI_STUDIO_API_KEY", "test")
        resolved = _resolve_providers(
            settings, ["ollama", "google", "hub"],
        )
        ids = [p.descriptor.id for p in resolved]
        assert ids == ["ollama", "google", "hub"]

    def test_unknown_provider_skipped(self, settings: SettingsManager):
        """Unknown provider IDs should be silently skipped."""
        resolved = _resolve_providers(settings, ["hub", "nonexistent"])
        assert len(resolved) == 1
        assert resolved[0].descriptor.id == "hub"

    def test_hub_reads_url_from_spoke_core(
        self, settings: SettingsManager,
    ):
        """Hub provider should use hub.url from spoke_core namespace."""
        settings.set("spoke_core", "hub.url", "http://myhost:9000")
        resolved = _resolve_providers(settings, ["hub"])
        assert resolved[0].api_base == "http://myhost:9000/api/v1"

    def test_ollama_reads_settings_from_tensorzero(
        self, settings: SettingsManager,
    ):
        """Ollama should use ollama.url and ollama.model from tensorzero."""
        settings.set(
            "tensorzero", "ollama.url", "http://gpu-box:11434/v1",
        )
        settings.set("tensorzero", "ollama.model", "mistral:7b")
        resolved = _resolve_providers(settings, ["ollama"])
        assert resolved[0].api_base == "http://gpu-box:11434/v1"
        assert resolved[0].model_name == "mistral:7b"


# ---------------------------------------------------------------------------
# TOML Generation
# ---------------------------------------------------------------------------


class TestTomlGeneration:
    """Tests for the full TOML output."""

    def test_generates_valid_toml_structure(
        self, settings: SettingsManager,
    ):
        """Generated TOML should have gateway, models, tools, functions."""
        toml = generate_toml(settings)
        assert "[gateway]" in toml
        assert "[tools.search_skills]" in toml
        assert "[tools.describe_function]" in toml
        assert "[tools.python_exec]" in toml

    def test_default_has_hub_and_ollama(
        self, settings: SettingsManager,
    ):
        """With default settings (no API keys), hub + ollama are present."""
        # Clear any env keys that might be set
        for key in [
            "GOOGLE_AI_STUDIO_API_KEY", "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
        ]:
            os.environ.pop(key, None)

        toml = generate_toml(settings)
        assert "[models.hub_gateway]" in toml
        assert "[models.ollama_local]" in toml
        assert "[functions.chat]" in toml
        assert "[functions.chat_local]" in toml
        # Cloud providers should NOT appear
        assert "[models.google_gemini]" not in toml
        assert "[models.openai_model]" not in toml

    def test_google_appears_when_key_set(
        self,
        settings: SettingsManager,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Google model should appear when API key is set."""
        monkeypatch.setenv("GOOGLE_AI_STUDIO_API_KEY", "test-key")
        toml = generate_toml(settings)
        assert "[models.google_gemini]" in toml
        assert "google_ai_studio_gemini" in toml

    def test_chat_function_hub_is_candidate(
        self, settings: SettingsManager,
    ):
        """In the 'chat' function, hub should be the candidate variant."""
        toml = generate_toml(settings)
        # Hub should be the candidate (first tried)
        assert 'candidate_variants = ["hub"]' in toml

    def test_chat_local_excludes_hub(
        self, settings: SettingsManager,
    ):
        """The 'chat_local' function should not include hub variant."""
        toml = generate_toml(settings)
        # Find the chat_local section and check hub is not there
        local_start = toml.find("[functions.chat_local]")
        assert local_start != -1
        local_section = toml[local_start:]
        assert "hub" not in local_section.split("[functions.chat_local.variants")[0]

    def test_custom_model_appears_with_full_config(
        self,
        settings: SettingsManager,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Custom provider should generate model + variant sections."""
        monkeypatch.setenv("CUSTOM_LLM_API_KEY", "sk-test")
        settings.set("tensorzero", "custom.model", "llama-3-70b")
        settings.set(
            "tensorzero", "custom.api_base", "https://api.together.xyz/v1",
        )
        settings.set(
            "tensorzero", "fallback_order",
            ["hub", "custom", "ollama"],
        )
        toml = generate_toml(settings)
        assert "[models.custom_model]" in toml
        assert "llama-3-70b" in toml
        assert "https://api.together.xyz/v1" in toml

    def test_auto_generated_header(self, settings: SettingsManager):
        """TOML should start with auto-generated warning."""
        toml = generate_toml(settings)
        assert "Auto-generated" in toml
        assert "do not edit manually" in toml

    def test_provider_timeout_in_toml(self, settings: SettingsManager):
        """Hub provider should have a timeout in the generated TOML."""
        toml = generate_toml(settings)
        assert "total_ms = 800" in toml

    def test_custom_fallback_order(
        self,
        settings: SettingsManager,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Custom fallback order should be respected."""
        monkeypatch.setenv("GOOGLE_AI_STUDIO_API_KEY", "test")
        # Put ollama before google
        settings.set(
            "tensorzero", "fallback_order",
            ["hub", "ollama", "google"],
        )
        toml = generate_toml(settings)
        # In the chat function, after hub candidate,
        # ollama should come before google in fallbacks
        chat_start = toml.find("[functions.chat]")
        chat_section = toml[chat_start:]
        ollama_pos = chat_section.find("local_ollama")
        google_pos = chat_section.find("google_variant")
        assert ollama_pos < google_pos


# ---------------------------------------------------------------------------
# Schema Registration
# ---------------------------------------------------------------------------


class TestSchemaRegistration:
    """Tests for tensorzero schema registration."""

    def test_schema_has_expected_groups(self):
        """Schema should have fallback, ollama, google, openai, anthropic, custom."""
        groups = {f.group for f in TENSORZERO_SCHEMA}
        assert groups == {
            "fallback", "ollama", "google", "openai", "anthropic", "custom",
        }

    def test_api_keys_are_secrets(self):
        """All API key fields should be marked as secrets."""
        api_key_fields = [
            f for f in TENSORZERO_SCHEMA if f.key.endswith(".api_key")
        ]
        assert len(api_key_fields) >= 3  # google, openai, anthropic
        for f in api_key_fields:
            assert f.secret, f"{f.key} should be secret"

    def test_register_idempotent(self, settings: SettingsManager):
        """Registering twice should not error."""
        register_tensorzero_schema(settings)
        register_tensorzero_schema(settings)
        assert settings.is_registered("tensorzero")

    def test_fallback_order_default(self, settings: SettingsManager):
        """Default fallback order should match DEFAULT_FALLBACK_ORDER."""
        order = settings.get(
            "tensorzero", "fallback_order", None,
        )
        assert order == DEFAULT_FALLBACK_ORDER
