

import pytest

from strawberry.shared.settings.manager import SettingsManager
from strawberry.shared.settings.schema import FieldType, SettingField
from strawberry.shared.settings.view_model import SettingsViewModel


@pytest.fixture
def settings_manager(tmp_path):
    return SettingsManager(config_dir=tmp_path, auto_save=False)

@pytest.fixture
def view_model(settings_manager):
    return SettingsViewModel(settings_manager)

def test_decoupled_provider_template(settings_manager, view_model):
    """Verify that provider sections can be generated using a template."""
    # 1. Register a provider namespace
    settings_manager.register(
        "plugins.image.flux",
        "Flux Image Gen",
        [SettingField("model", "Model", FieldType.TEXT, default="flux-pro")]
    )

    # 2. Register a consumer with a TEMPLATE
    schema = [
        SettingField(
            "backend",
            "Image Backend",
            FieldType.PROVIDER_SELECT,
            provider_type="image",
            default="flux",
            provider_namespace_template="plugins.image.{value}" # <--- The new feature
        )
    ]
    settings_manager.register("image_core", "Image Core", schema)

    # 3. Validation: Verify view model uses the template
    sections = view_model.get_provider_sections("image_core")

    assert len(sections) == 1
    # Default empty value usually maps to nothing; expect logic handles it or we set value first.
    assert sections[0].provider_settings_namespace == "plugins.image.flux"

    # Let's set the value to 'flux' to be sure
    settings_manager.set("image_core", "backend", "flux")
    sections = view_model.get_provider_sections("image_core")
    assert sections[0].provider_settings_namespace == "plugins.image.flux"


def test_field_type_list(settings_manager):
    """Verify FieldType.LIST support."""
    schema = [
        SettingField("items", "My Items", FieldType.LIST, default=["a", "b"])
    ]
    settings_manager.register("list_test", "List Test", schema)

    # Verify default
    assert settings_manager.get("list_test", "items") == ["a", "b"]

    # Verify update
    settings_manager.set("list_test", "items", ["c"])
    assert settings_manager.get("list_test", "items") == ["c"]

def test_external_validation(settings_manager):
    """Verify external validation callbacks."""
    schema = [
        SettingField("age", "Age", FieldType.NUMBER)
    ]
    settings_manager.register("validation_test", "Test", schema)

    # Register validator
    def validate_age(value):
        if value < 0:
            return "Age cannot be negative"
        return None

    # Assuming the API will be register_validator(namespace, key, callback)
    settings_manager.register_validator("validation_test", "age", validate_age)

    # Test valid
    error = settings_manager.set("validation_test", "age", 10)
    assert error is None

    # Test invalid
    error = settings_manager.set("validation_test", "age", -5)
    assert error == "Age cannot be negative"

def test_metadata_field():
    """Verify that metadata is correctly stored in SettingField."""
    field = SettingField(
        "test_key",
        "Test Label",
        FieldType.TEXT,
        metadata={"help_text": "Some help"}
    )
    assert field.metadata == {"help_text": "Some help"}
