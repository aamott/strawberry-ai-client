"""Tests for the SettingsManager.

Tests the core settings management functionality including:
- Namespace registration
- Value get/set
- Persistence to YAML and .env files
- Change events
- Schema validation
"""

import tempfile
from pathlib import Path

import pytest

from strawberry.shared.settings import (
    FieldType,
    SettingField,
    SettingsManager,
    SettingsViewModel,
)


@pytest.fixture
def temp_config_dir():
    """Create a temporary config directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def settings_manager(temp_config_dir):
    """Create a SettingsManager with a temp config directory."""
    return SettingsManager(config_dir=temp_config_dir)


@pytest.fixture
def sample_schema():
    """Create a sample settings schema."""
    return [
        SettingField(
            key="name",
            label="Name",
            type=FieldType.TEXT,
            default="default_name",
            group="general",
        ),
        SettingField(
            key="api_key",
            label="API Key",
            type=FieldType.PASSWORD,
            secret=True,
            group="auth",
        ),
        SettingField(
            key="enabled",
            label="Enabled",
            type=FieldType.CHECKBOX,
            default=True,
            group="general",
        ),
        SettingField(
            key="count",
            label="Count",
            type=FieldType.NUMBER,
            default=10,
            min_value=0,
            max_value=100,
            group="general",
        ),
        SettingField(
            key="mode",
            label="Mode",
            type=FieldType.SELECT,
            options=["fast", "normal", "slow"],
            default="normal",
            group="general",
        ),
    ]


class TestSettingsManager:
    """Tests for SettingsManager class."""

    def test_register_namespace(self, settings_manager, sample_schema):
        """Test registering a settings namespace."""
        settings_manager.register(
            namespace="test",
            display_name="Test",
            schema=sample_schema,
            order=10,
        )

        assert settings_manager.is_registered("test")
        namespaces = settings_manager.get_namespaces()
        assert len(namespaces) == 1
        assert namespaces[0].name == "test"
        assert namespaces[0].display_name == "Test"

    def test_duplicate_namespace_raises(self, settings_manager, sample_schema):
        """Test that registering duplicate namespace raises error."""
        settings_manager.register("test", "Test", sample_schema)

        with pytest.raises(ValueError, match="already registered"):
            settings_manager.register("test", "Test 2", sample_schema)

    def test_get_set_values(self, settings_manager, sample_schema):
        """Test getting and setting values."""
        settings_manager.register("test", "Test", sample_schema)

        # Test defaults are applied
        assert settings_manager.get("test", "name") == "default_name"
        assert settings_manager.get("test", "enabled") is True
        assert settings_manager.get("test", "count") == 10

        # Test setting values
        settings_manager.set("test", "name", "new_name")
        assert settings_manager.get("test", "name") == "new_name"

        settings_manager.set("test", "enabled", False)
        assert settings_manager.get("test", "enabled") is False

    def test_get_all(self, settings_manager, sample_schema):
        """Test getting all values for a namespace."""
        settings_manager.register("test", "Test", sample_schema)
        settings_manager.set("test", "name", "my_name")

        values = settings_manager.get_all("test")
        assert values["name"] == "my_name"
        assert values["enabled"] is True
        assert values["count"] == 10

    def test_update_multiple(self, settings_manager, sample_schema):
        """Test updating multiple values at once."""
        settings_manager.register("test", "Test", sample_schema)

        errors = settings_manager.update(
            "test",
            {
                "name": "updated",
                "count": 50,
            },
        )

        assert errors == {}
        assert settings_manager.get("test", "name") == "updated"
        assert settings_manager.get("test", "count") == 50

    def test_validation(self, settings_manager, sample_schema):
        """Test field validation."""
        settings_manager.register("test", "Test", sample_schema)

        # Valid value
        error = settings_manager.set("test", "count", 50)
        assert error is None

        # Invalid value (out of range)
        error = settings_manager.set("test", "count", 200)
        assert error is not None
        assert "at most" in error.lower()

        # Invalid value for select
        error = settings_manager.set("test", "mode", "invalid")
        assert error is not None
        assert "must be one of" in error.lower()

    def test_secret_storage(self, settings_manager, sample_schema, temp_config_dir):
        """Test that secrets are stored in .env file."""
        settings_manager.register("test", "Test", sample_schema)
        settings_manager.set("test", "api_key", "secret123")
        settings_manager.set("test", "name", "public_name")

        # Check .env file contains secret
        env_file = temp_config_dir / ".env"
        assert env_file.exists()
        env_content = env_file.read_text()
        assert "secret123" in env_content

        # Check YAML file does not contain secret
        yaml_file = temp_config_dir / "settings.yaml"
        yaml_content = yaml_file.read_text()
        assert "secret123" not in yaml_content
        assert "public_name" in yaml_content

    def test_change_events(self, settings_manager, sample_schema):
        """Test that change events are emitted."""
        settings_manager.register("test", "Test", sample_schema)

        received_events = []

        def listener(ns, key, val):
            received_events.append((ns, key, val))

        settings_manager.on_change(listener)
        settings_manager.set("test", "name", "event_test")

        assert len(received_events) == 1
        assert received_events[0] == ("test", "name", "event_test")

    def test_get_schema(self, settings_manager, sample_schema):
        """Test getting schema for a namespace."""
        settings_manager.register("test", "Test", sample_schema)

        schema = settings_manager.get_schema("test")
        assert len(schema) == 5
        assert schema[0].key == "name"

    def test_get_field(self, settings_manager, sample_schema):
        """Test getting a specific field."""
        settings_manager.register("test", "Test", sample_schema)

        field = settings_manager.get_field("test", "name")
        assert field is not None
        assert field.label == "Name"
        assert field.type == FieldType.TEXT

        # Non-existent field
        assert settings_manager.get_field("test", "nonexistent") is None

    def test_is_secret(self, settings_manager, sample_schema):
        """Test checking if a field is a secret."""
        settings_manager.register("test", "Test", sample_schema)

        assert settings_manager.is_secret("test", "api_key") is True
        assert settings_manager.is_secret("test", "name") is False

    def test_options_provider(self, settings_manager):
        """Test dynamic options provider."""
        schema = [
            SettingField(
                key="model",
                label="Model",
                type=FieldType.DYNAMIC_SELECT,
                options_provider="get_models",
            ),
        ]
        settings_manager.register("test", "Test", schema)

        def get_models():
            return ["model1", "model2", "model3"]

        settings_manager.register_options_provider("get_models", get_models)

        options = settings_manager.get_options("get_models")
        assert options == ["model1", "model2", "model3"]

    def test_reload(self, settings_manager, sample_schema, temp_config_dir):
        """Test reloading settings from disk."""
        settings_manager.register("test", "Test", sample_schema)
        settings_manager.set("test", "name", "before_reload")

        # Manually modify the file
        yaml_file = temp_config_dir / "settings.yaml"
        content = yaml_file.read_text()
        content = content.replace("before_reload", "after_reload")
        yaml_file.write_text(content)

        # Reload and check
        settings_manager.reload()
        assert settings_manager.get("test", "name") == "after_reload"


class TestSettingsViewModel:
    """Tests for SettingsViewModel class."""

    def test_get_sections(self, settings_manager, sample_schema):
        """Test getting sections for UI."""
        settings_manager.register("ns1", "Namespace 1", sample_schema, order=10)
        settings_manager.register("ns2", "Namespace 2", sample_schema, order=20)

        view_model = SettingsViewModel(settings_manager)
        sections = view_model.get_sections()

        assert len(sections) == 2
        assert sections[0].namespace == "ns1"
        assert sections[1].namespace == "ns2"

    def test_get_section(self, settings_manager, sample_schema):
        """Test getting a specific section."""
        settings_manager.register("test", "Test", sample_schema)
        settings_manager.set("test", "name", "test_value")

        view_model = SettingsViewModel(settings_manager)
        section = view_model.get_section("test")

        assert section is not None
        assert section.display_name == "Test"
        assert section.values["name"] == "test_value"
        assert "general" in section.groups
        assert "auth" in section.groups

    def test_provider_sections(self, settings_manager):
        """Test provider sections for voice backends using explicit PROVIDER_SELECT."""
        # Create voice_core schema with explicit PROVIDER_SELECT fields
        voice_schema = [
            SettingField(
                key="stt.order",
                label="STT Order",
                type=FieldType.PROVIDER_SELECT,
                default="whisper,google",
                group="stt",
                provider_type="stt",
                provider_namespace_template="voice.stt.{value}",
            ),
            SettingField(
                key="tts.order",
                label="TTS Order",
                type=FieldType.PROVIDER_SELECT,
                default="piper,google",
                group="tts",
                provider_type="tts",
                provider_namespace_template="voice.tts.{value}",
            ),
        ]

        # Create provider schemas
        whisper_schema = [
            SettingField(
                key="model_size",
                label="Model Size",
                type=FieldType.SELECT,
                options=["tiny", "base", "small"],
                default="base",
            ),
        ]

        settings_manager.register("voice_core", "Voice", voice_schema, order=20)
        settings_manager.register(
            "voice.stt.whisper", "STT: Whisper", whisper_schema, order=100
        )

        view_model = SettingsViewModel(settings_manager)
        providers = view_model.get_provider_sections("voice_core")

        assert len(providers) >= 1
        stt_provider = next((p for p in providers if "stt" in p.provider_key), None)
        assert stt_provider is not None
        assert stt_provider.selected_provider == "whisper"

    def test_set_primary_provider(self, settings_manager):
        """Test setting the primary provider."""
        voice_schema = [
            SettingField(
                key="stt.order",
                label="STT Order",
                type=FieldType.TEXT,
                default="whisper,google,leopard",
                group="stt",
            ),
        ]
        settings_manager.register("voice_core", "Voice", voice_schema)

        view_model = SettingsViewModel(settings_manager)

        # Set google as primary
        view_model.set_primary_provider("voice_core", "stt.order", "google")

        order = view_model.get_provider_order("voice_core", "stt.order")
        assert order[0] == "google"
        assert "whisper" in order
        assert "leopard" in order

    def test_validate_field(self, settings_manager, sample_schema):
        """Test field validation via view model."""
        settings_manager.register("test", "Test", sample_schema)
        view_model = SettingsViewModel(settings_manager)

        # Valid value
        result = view_model.validate_field("test", "count", 50)
        assert result.valid is True

        # Invalid value
        result = view_model.validate_field("test", "count", 200)
        assert result.valid is False
        assert result.error is not None
