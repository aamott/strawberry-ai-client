"""Factory for creating GUI V2 field widgets based on FieldType."""

from typing import Any, Optional

from PySide6.QtWidgets import QWidget

from strawberry.shared.settings import FieldType, SettingField

from .field_base import BaseFieldWidget


def create_field_widget(
    field: SettingField,
    current_value: Any = None,
    parent: Optional[QWidget] = None,
) -> BaseFieldWidget:
    """Create appropriate widget for field type.

    Args:
        field: The field definition.
        current_value: Current value.
        parent: Parent widget.

    Returns:
        The appropriate field widget.
    """
    # Import here to avoid circular imports
    from .field_advanced import (
        ActionFieldWidget,
        ColorFieldWidget,
        DateTimeFieldWidget,
        ListFieldWidget,
        MultilineFieldWidget,
        PathFieldWidget,
        ProviderOrderWidget,
        SliderFieldWidget,
    )
    from .field_simple import (
        CheckboxFieldWidget,
        NumberFieldWidget,
        PasswordFieldWidget,
        SelectFieldWidget,
        TextFieldWidget,
    )

    widget_map = {
        FieldType.TEXT: TextFieldWidget,
        FieldType.PASSWORD: PasswordFieldWidget,
        FieldType.NUMBER: NumberFieldWidget,
        FieldType.CHECKBOX: CheckboxFieldWidget,
        FieldType.SELECT: SelectFieldWidget,
        FieldType.DYNAMIC_SELECT: SelectFieldWidget,
        FieldType.MULTILINE: MultilineFieldWidget,
        FieldType.ACTION: ActionFieldWidget,
        FieldType.LIST: ListFieldWidget,
        FieldType.PROVIDER_SELECT: ProviderOrderWidget,
        FieldType.FILE_PATH: PathFieldWidget,
        FieldType.DIRECTORY_PATH: PathFieldWidget,
        FieldType.COLOR: ColorFieldWidget,
        FieldType.SLIDER: SliderFieldWidget,
        FieldType.DATE: DateTimeFieldWidget,
        FieldType.TIME: DateTimeFieldWidget,
        FieldType.DATETIME: DateTimeFieldWidget,
    }

    widget_class = widget_map.get(field.type, TextFieldWidget)
    return widget_class(field, current_value, parent)
