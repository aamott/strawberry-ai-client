"""Simple field widgets for GUI V2 settings.

Covers: TEXT, PASSWORD, NUMBER, CHECKBOX, SELECT, DYNAMIC_SELECT
"""

from typing import Any, List, Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from ....shared.settings import SettingField
from .field_base import BaseFieldWidget

# Shared input styling for dark theme
_INPUT_STYLE = """
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
        background-color: #1e1e3f;
        color: #ffffff;
        border: 1px solid #2a2a4a;
        border-radius: 6px;
        padding: 6px 10px;
        font-size: 13px;
    }
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
        border-color: #e94560;
    }
    QComboBox::drop-down {
        border: none;
        padding-right: 8px;
    }
    QComboBox::down-arrow {
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 6px solid #a0a0a0;
        margin-right: 6px;
    }
    QComboBox QAbstractItemView {
        background-color: #1e1e3f;
        color: #ffffff;
        border: 1px solid #2a2a4a;
        selection-background-color: #3a3a5a;
    }
"""

_CHECKBOX_STYLE = """
    QCheckBox {
        color: #ffffff;
        spacing: 8px;
    }
    QCheckBox::indicator {
        width: 18px;
        height: 18px;
        border: 2px solid #2a2a4a;
        border-radius: 4px;
        background-color: #1e1e3f;
    }
    QCheckBox::indicator:checked {
        background-color: #e94560;
        border-color: #e94560;
    }
    QCheckBox::indicator:hover {
        border-color: #3a3a5a;
    }
"""


class TextFieldWidget(BaseFieldWidget):
    """Text input field (QLineEdit)."""

    def _build_input(self) -> None:
        self._line_edit = QLineEdit()
        self._line_edit.setPlaceholderText(self.field.placeholder or "")
        self._line_edit.setStyleSheet(_INPUT_STYLE)
        self._line_edit.textChanged.connect(self._on_value_changed)
        self._input_layout.addWidget(self._line_edit)

    def get_value(self) -> str:
        return self._line_edit.text()

    def set_value(self, value: Any) -> None:
        self._line_edit.setText(str(value) if value is not None else "")


class PasswordFieldWidget(BaseFieldWidget):
    """Password input field (masked QLineEdit)."""

    def _build_input(self) -> None:
        self._line_edit = QLineEdit()
        self._line_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._line_edit.setPlaceholderText(self.field.placeholder or "Enter secret...")
        self._line_edit.setStyleSheet(_INPUT_STYLE)
        self._line_edit.textChanged.connect(self._on_value_changed)
        self._input_layout.addWidget(self._line_edit)

    def get_value(self) -> str:
        return self._line_edit.text()

    def set_value(self, value: Any) -> None:
        self._line_edit.setText(str(value) if value is not None else "")


class NumberFieldWidget(BaseFieldWidget):
    """Number input field (QSpinBox or QDoubleSpinBox)."""

    def _build_input(self) -> None:
        # Determine if float or int based on default/min/max
        is_float = any(
            [
                isinstance(self.field.default, float),
                isinstance(self.field.min_value, float),
                isinstance(self.field.max_value, float),
            ]
        )

        if is_float:
            self._spin = QDoubleSpinBox()
            self._spin.setDecimals(2)
        else:
            self._spin = QSpinBox()

        # Set range
        min_val = self.field.min_value if self.field.min_value is not None else -999999
        max_val = self.field.max_value if self.field.max_value is not None else 999999
        self._spin.setMinimum(int(min_val) if not is_float else min_val)
        self._spin.setMaximum(int(max_val) if not is_float else max_val)

        self._spin.setStyleSheet(_INPUT_STYLE)
        self._spin.valueChanged.connect(self._on_value_changed)
        self._input_layout.addWidget(self._spin)

    def get_value(self) -> float | int:
        return self._spin.value()

    def set_value(self, value: Any) -> None:
        if value is not None:
            try:
                if isinstance(self._spin, QDoubleSpinBox):
                    self._spin.setValue(float(value))
                else:
                    self._spin.setValue(int(value))
            except (ValueError, TypeError):
                pass


class CheckboxFieldWidget(BaseFieldWidget):
    """Checkbox field (QCheckBox)."""

    def _build_input(self) -> None:
        self._checkbox = QCheckBox()
        self._checkbox.setStyleSheet(_CHECKBOX_STYLE)
        self._checkbox.stateChanged.connect(self._on_value_changed)
        self._input_layout.addWidget(self._checkbox)

    def get_value(self) -> bool:
        return self._checkbox.isChecked()

    def set_value(self, value: Any) -> None:
        self._checkbox.setChecked(bool(value))


class SelectFieldWidget(BaseFieldWidget):
    """Dropdown select field (QComboBox).

    Works for both SELECT (static options) and DYNAMIC_SELECT (runtime options).
    """

    def __init__(
        self,
        field: SettingField,
        current_value: Any = None,
        parent: Optional[QWidget] = None,
        options: Optional[List[str]] = None,
    ):
        """Initialize select widget.

        Args:
            field: Field definition.
            current_value: Current value.
            parent: Parent widget.
            options: Override options (for DYNAMIC_SELECT populated at runtime).
        """
        self._dynamic_options = options
        super().__init__(field, current_value, parent)

    def _build_input(self) -> None:
        self._combo = QComboBox()
        self._combo.setStyleSheet(_INPUT_STYLE)

        # Populate options
        options = self._dynamic_options or self.field.options or []
        self._combo.addItems(options)

        self._combo.currentTextChanged.connect(self._on_value_changed)
        self._input_layout.addWidget(self._combo)

    def get_value(self) -> str:
        return self._combo.currentText()

    def set_value(self, value: Any) -> None:
        if value is not None:
            idx = self._combo.findText(str(value))
            if idx >= 0:
                self._combo.setCurrentIndex(idx)
            else:
                # Value not in options — add it temporarily
                self._combo.addItem(str(value))
                self._combo.setCurrentText(str(value))

    def set_options(self, options: List[str]) -> None:
        """Update available options (for DYNAMIC_SELECT).

        Args:
            options: New list of options.
        """
        current = self.get_value()
        self._combo.clear()
        self._combo.addItems(options)
        self.set_value(current)
