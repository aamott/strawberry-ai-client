"""Base field widget for settings UI.

All field widgets inherit from this base class.
"""

from abc import abstractmethod
from typing import Any, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from strawberry.shared.settings import SettingField


class BaseFieldWidget(QWidget):
    """Base class for all field widgets.

    Provides common functionality for field rendering including:
    - Label display
    - Description tooltip
    - Validation styling (red glow for invalid)
    - Reset to default button
    - Value change signal

    Subclasses must implement:
    - _build_input(): Create the input widget(s)
    - get_value(): Return current value
    - set_value(): Set widget value
    """

    # Emits new value when user changes input
    value_changed = Signal(object)

    def __init__(
        self,
        field: SettingField,
        current_value: Any = None,
        parent: Optional[QWidget] = None,
    ):
        """Initialize field widget.

        Args:
            field: The field definition from schema.
            current_value: Current value (or default if None).
            parent: Parent widget.
        """
        super().__init__(parent)
        self.field = field
        self._default_value = field.default
        self._current_value = (
            current_value if current_value is not None else field.default
        )
        self._is_valid = True

        self._build_ui()

    def _build_ui(self) -> None:
        """Build the widget UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)

        # Row with label, input, and reset button
        row = QHBoxLayout()
        row.setSpacing(8)

        # Label
        self._label = QLabel(self.field.label)
        self._label.setMinimumWidth(150)
        row.addWidget(self._label)

        # Input widget (implemented by subclass)
        self._input_container = QWidget()
        self._input_layout = QHBoxLayout(self._input_container)
        self._input_layout.setContentsMargins(0, 0, 0, 0)
        self._build_input()
        row.addWidget(self._input_container, stretch=1)

        # Reset button (only shown when value differs from default)
        self._reset_btn = QPushButton("↺")
        self._reset_btn.setFixedWidth(24)
        self._reset_btn.setToolTip(f"Reset to default: {self._default_value}")
        self._reset_btn.clicked.connect(self._on_reset_clicked)
        self._reset_btn.setVisible(False)
        row.addWidget(self._reset_btn)

        layout.addLayout(row)

        # Description (if present)
        if self.field.description:
            desc_label = QLabel(self.field.description)
            desc_label.setStyleSheet("color: gray; font-size: 11px; margin-left: 158px;")
            desc_label.setWordWrap(True)
            layout.addWidget(desc_label)

        # Warning/error message label (hidden by default)
        self._message_label = QLabel()
        self._message_label.setWordWrap(True)
        self._message_label.setStyleSheet("margin-left: 158px;")
        self._message_label.setVisible(False)
        layout.addWidget(self._message_label)

        # Set tooltip
        if self.field.description:
            self.setToolTip(self.field.description)

        # Initialize with current value
        self.set_value(self._current_value)
        self._update_reset_visibility()

    @abstractmethod
    def _build_input(self) -> None:
        """Build the input widget(s). Must add widgets to self._input_layout."""
        pass

    @abstractmethod
    def get_value(self) -> Any:
        """Get current widget value.

        Returns:
            The current value.
        """
        pass

    @abstractmethod
    def set_value(self, value: Any) -> None:
        """Set widget value.

        Args:
            value: The value to set.
        """
        pass

    def _on_value_changed(self) -> None:
        """Called when input value changes. Subclasses should call this."""
        self._update_reset_visibility()
        self.value_changed.emit(self.get_value())

    def _on_reset_clicked(self) -> None:
        """Reset to default value."""
        self.set_value(self._default_value)
        self._on_value_changed()

    def _update_reset_visibility(self) -> None:
        """Show/hide reset button based on value."""
        current = self.get_value()
        differs = current != self._default_value
        self._reset_btn.setVisible(differs)

    def set_invalid(self, message: str) -> None:
        """Apply red border and show error message.

        Args:
            message: Error message to display.
        """
        self._is_valid = False
        self._input_container.setStyleSheet("""
            QWidget {
                border: 2px solid #ff4444;
                border-radius: 4px;
            }
        """)
        self._input_container.setToolTip(f"⚠ {message}")
        # Show visible error message
        self._message_label.setText(f"⚠ {message}")
        self._message_label.setStyleSheet(
            "color: #ff4444; font-size: 11px; margin-left: 158px;"
        )
        self._message_label.setVisible(True)

    def set_valid(self) -> None:
        """Clear validation styling and hide message."""
        self._is_valid = True
        self._input_container.setStyleSheet("")
        self._input_container.setToolTip(self.field.description or "")
        self._message_label.setVisible(False)

    def set_warning(self, message: str) -> None:
        """Apply orange border and show warning message.

        Args:
            message: Warning message to display.
        """
        self._input_container.setStyleSheet("""
            QWidget {
                border: 2px solid #ffaa00;
                border-radius: 4px;
            }
        """)
        self._input_container.setToolTip(f"⚠ {message}")
        # Show visible warning message
        self._message_label.setText(f"⚠ {message}")
        self._message_label.setStyleSheet(
            "color: #cc8800; font-size: 11px; margin-left: 158px;"
        )
        self._message_label.setVisible(True)

    def clear_warning(self) -> None:
        """Clear warning styling and hide message."""
        self._input_container.setStyleSheet("")
        self._input_container.setToolTip(self.field.description or "")
        self._message_label.setVisible(False)

    @property
    def is_valid(self) -> bool:
        """Check if field is currently valid."""
        return self._is_valid

    @property
    def has_changes(self) -> bool:
        """Check if value differs from default."""
        return self.get_value() != self._default_value
