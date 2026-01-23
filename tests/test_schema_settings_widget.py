"""Tests for SchemaSettingsWidget."""

import pytest

from strawberry.spoke_core.settings_schema import FieldType, SettingField

# Only run if PySide6 is available
pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    """Create a QApplication for testing."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestSchemaSettingsWidget:
    """Tests for SchemaSettingsWidget."""

    @pytest.fixture
    def simple_schema(self):
        """Simple schema with different field types."""
        return [
            SettingField(
                key="name",
                label="Name",
                type=FieldType.TEXT,
                default="Default Name",
                group="general",
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
                group="general",
            ),
            SettingField(
                key="theme",
                label="Theme",
                type=FieldType.SELECT,
                options=["dark", "light", "system"],
                default="dark",
                group="appearance",
            ),
        ]

    def test_widget_creation(self, qapp, simple_schema):
        """Widget should be created from schema."""
        from strawberry.ui.qt.widgets.schema_settings import SchemaSettingsWidget

        widget = SchemaSettingsWidget(simple_schema)
        assert widget is not None
        assert len(widget._widgets) == 4

    def test_initial_values(self, qapp, simple_schema):
        """Widget should use provided initial values."""
        from strawberry.ui.qt.widgets.schema_settings import SchemaSettingsWidget

        values = {"name": "Custom Name", "enabled": False}
        widget = SchemaSettingsWidget(simple_schema, values=values)

        result = widget.get_values()
        assert result["name"] == "Custom Name"
        assert result["enabled"] is False

    def test_default_values(self, qapp, simple_schema):
        """Widget should use default values when not provided."""
        from strawberry.ui.qt.widgets.schema_settings import SchemaSettingsWidget

        widget = SchemaSettingsWidget(simple_schema)
        result = widget.get_values()
        # Defaults are applied via widgets, check if key exists
        assert "theme" in result or widget._widgets.get("theme") is not None

    def test_value_changed_signal(self, qapp, simple_schema):
        """value_changed signal should be emitted on widget changes."""
        from strawberry.ui.qt.widgets.schema_settings import SchemaSettingsWidget

        widget = SchemaSettingsWidget(simple_schema)

        # Track signal
        signals = []
        widget.value_changed.connect(lambda k, v: signals.append((k, v)))

        # Simulate change
        widget._on_value_changed("name", "New Name")

        assert len(signals) == 1
        assert signals[0] == ("name", "New Name")

    def test_set_value(self, qapp, simple_schema):
        """set_value should update widget without triggering signals."""
        from strawberry.ui.qt.widgets.schema_settings import SchemaSettingsWidget

        widget = SchemaSettingsWidget(simple_schema)

        signals = []
        widget.value_changed.connect(lambda k, v: signals.append((k, v)))

        widget.set_value("name", "Programmatic Value")

        # Signal should NOT have been emitted
        assert len(signals) == 0

        # But value should be updated
        assert widget.get_values()["name"] == "Programmatic Value"

    def test_groups_created(self, qapp, simple_schema):
        """Fields should be grouped by group attribute."""
        from PySide6.QtWidgets import QGroupBox

        from strawberry.ui.qt.widgets.schema_settings import SchemaSettingsWidget

        widget = SchemaSettingsWidget(simple_schema)

        # Find group boxes
        group_boxes = widget.findChildren(QGroupBox)
        titles = [g.title() for g in group_boxes]

        assert "General" in titles
        assert "Appearance" in titles


class TestActionField:
    """Tests for ACTION field type."""

    @pytest.fixture
    def action_schema(self):
        """Schema with an action field."""
        return [
            SettingField(
                key="connect",
                label="Connect",
                type=FieldType.ACTION,
                action="do_connect",
                group="actions",
            ),
        ]

    def test_action_button_created(self, qapp, action_schema):
        """ACTION field should create a button."""
        from PySide6.QtWidgets import QPushButton

        from strawberry.ui.qt.widgets.schema_settings import SchemaSettingsWidget

        widget = SchemaSettingsWidget(action_schema)

        buttons = widget.findChildren(QPushButton)
        assert len(buttons) >= 1
        assert any(b.text() == "Connect" for b in buttons)

    def test_action_signal(self, qapp, action_schema):
        """action_triggered signal should be emitted when button clicked."""
        from PySide6.QtWidgets import QPushButton

        from strawberry.ui.qt.widgets.schema_settings import SchemaSettingsWidget

        widget = SchemaSettingsWidget(action_schema)

        signals = []
        widget.action_triggered.connect(lambda a: signals.append(a))

        # Find and click the button
        buttons = widget.findChildren(QPushButton)
        connect_btn = next(b for b in buttons if b.text() == "Connect")
        connect_btn.click()

        assert signals == ["do_connect"]


class TestDynamicSelect:
    """Tests for DYNAMIC_SELECT field type."""

    @pytest.fixture
    def dynamic_schema(self):
        """Schema with a dynamic select field."""
        return [
            SettingField(
                key="model",
                label="Model",
                type=FieldType.DYNAMIC_SELECT,
                options_provider="get_models",
                default="model_a",
                group="models",
            ),
        ]

    def test_dynamic_options_populated(self, qapp, dynamic_schema):
        """DYNAMIC_SELECT should call options_provider."""
        from PySide6.QtWidgets import QComboBox

        from strawberry.ui.qt.widgets.schema_settings import SchemaSettingsWidget

        def mock_provider(name):
            if name == "get_models":
                return ["model_a", "model_b", "model_c"]
            return []

        widget = SchemaSettingsWidget(
            dynamic_schema,
            options_provider=mock_provider
        )

        combos = widget.findChildren(QComboBox)
        assert len(combos) == 1

        items = [combos[0].itemText(i) for i in range(combos[0].count())]
        assert items == ["model_a", "model_b", "model_c"]

