"""Tests for settings schema module."""

import pytest

from strawberry.core.settings_schema import (
    ActionResult,
    FieldType,
    SettingField,
    CORE_SETTINGS_SCHEMA,
    get_field_by_key,
    group_fields,
)


class TestFieldType:
    """Tests for FieldType enum."""
    
    def test_all_types_have_string_values(self):
        """All field types should have string values for serialization."""
        for field_type in FieldType:
            assert isinstance(field_type.value, str)
    
    def test_expected_types_exist(self):
        """All expected field types should be defined."""
        expected = ["text", "password", "number", "checkbox", "select", "dynamic_select", "action"]
        actual = [ft.value for ft in FieldType]
        for exp in expected:
            assert exp in actual, f"Missing field type: {exp}"


class TestSettingField:
    """Tests for SettingField dataclass."""
    
    def test_basic_text_field(self):
        """Basic text field should be created successfully."""
        field = SettingField(
            key="test.field",
            label="Test Field",
            type=FieldType.TEXT,
            default="default_value",
        )
        assert field.key == "test.field"
        assert field.label == "Test Field"
        assert field.type == FieldType.TEXT
        assert field.default == "default_value"
        assert field.group == "general"  # default group
    
    def test_select_field_requires_options(self):
        """SELECT field must have options defined."""
        with pytest.raises(ValueError, match="SELECT type requires options"):
            SettingField(
                key="test.select",
                label="Test Select",
                type=FieldType.SELECT,
            )
    
    def test_select_field_with_options(self):
        """SELECT field with options should be valid."""
        field = SettingField(
            key="test.select",
            label="Test Select",
            type=FieldType.SELECT,
            options=["opt1", "opt2", "opt3"],
        )
        assert field.options == ["opt1", "opt2", "opt3"]
    
    def test_dynamic_select_requires_provider(self):
        """DYNAMIC_SELECT field must have options_provider."""
        with pytest.raises(ValueError, match="DYNAMIC_SELECT type requires options_provider"):
            SettingField(
                key="test.dynamic",
                label="Test Dynamic",
                type=FieldType.DYNAMIC_SELECT,
            )
    
    def test_dynamic_select_with_provider(self):
        """DYNAMIC_SELECT field with provider should be valid."""
        field = SettingField(
            key="test.dynamic",
            label="Test Dynamic",
            type=FieldType.DYNAMIC_SELECT,
            options_provider="get_options",
        )
        assert field.options_provider == "get_options"
    
    def test_action_requires_action_name(self):
        """ACTION field must have action defined."""
        with pytest.raises(ValueError, match="ACTION type requires action"):
            SettingField(
                key="test.action",
                label="Test Action",
                type=FieldType.ACTION,
            )
    
    def test_action_with_action_name(self):
        """ACTION field with action name should be valid."""
        field = SettingField(
            key="test.action",
            label="Test Action",
            type=FieldType.ACTION,
            action="do_something",
        )
        assert field.action == "do_something"
    
    def test_password_field_with_secret(self):
        """PASSWORD field typically has secret=True."""
        field = SettingField(
            key="api.key",
            label="API Key",
            type=FieldType.PASSWORD,
            secret=True,
        )
        assert field.secret is True
    
    def test_field_with_depends_on(self):
        """Field can have a conditional dependency."""
        field = SettingField(
            key="advanced.setting",
            label="Advanced Setting",
            type=FieldType.TEXT,
            depends_on="advanced.enabled",
        )
        assert field.depends_on == "advanced.enabled"


class TestActionResult:
    """Tests for ActionResult dataclass."""
    
    def test_success_result(self):
        """Success result should have correct type."""
        result = ActionResult(
            type="success",
            message="Operation completed",
        )
        assert result.type == "success"
        assert result.message == "Operation completed"
        assert result.pending is False
    
    def test_browser_result(self):
        """Open browser result should have URL."""
        result = ActionResult(
            type="open_browser",
            url="https://example.com/auth",
            message="Redirecting to login...",
            pending=True,
        )
        assert result.type == "open_browser"
        assert result.url == "https://example.com/auth"
        assert result.pending is True


class TestCoreSettingsSchema:
    """Tests for CORE_SETTINGS_SCHEMA."""
    
    def test_schema_not_empty(self):
        """Core settings schema should have fields."""
        assert len(CORE_SETTINGS_SCHEMA) > 0
    
    def test_all_fields_valid(self):
        """All fields in core schema should be valid SettingField instances."""
        for field in CORE_SETTINGS_SCHEMA:
            assert isinstance(field, SettingField)
            assert field.key
            assert field.label
            assert isinstance(field.type, FieldType)
    
    def test_has_device_name(self):
        """Should have device name field."""
        field = get_field_by_key(CORE_SETTINGS_SCHEMA, "device.name")
        assert field is not None
        assert field.type == FieldType.TEXT
    
    def test_has_hub_settings(self):
        """Should have hub connection fields."""
        hub_url = get_field_by_key(CORE_SETTINGS_SCHEMA, "hub.url")
        hub_token = get_field_by_key(CORE_SETTINGS_SCHEMA, "hub.token")
        assert hub_url is not None
        assert hub_token is not None
        assert hub_token.secret is True


class TestHelperFunctions:
    """Tests for schema helper functions."""
    
    def test_get_field_by_key_found(self):
        """get_field_by_key should find existing field."""
        field = get_field_by_key(CORE_SETTINGS_SCHEMA, "device.name")
        assert field is not None
        assert field.label == "Device Name"
    
    def test_get_field_by_key_not_found(self):
        """get_field_by_key should return None for missing field."""
        field = get_field_by_key(CORE_SETTINGS_SCHEMA, "nonexistent.field")
        assert field is None
    
    def test_group_fields(self):
        """group_fields should organize fields by group."""
        groups = group_fields(CORE_SETTINGS_SCHEMA)
        assert isinstance(groups, dict)
        assert "general" in groups
        assert "hub" in groups
        assert all(isinstance(f, SettingField) for f in groups["general"])
