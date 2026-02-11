"""Advanced field widgets for GUI V2 settings.

Covers: MULTILINE, ACTION, LIST, PROVIDER_SELECT, FILE_PATH, DIRECTORY_PATH,
        COLOR, SLIDER, DATE, TIME, DATETIME
"""

from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QDate, QDateTime, Qt, QTime
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QDateEdit,
    QDateTimeEdit,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from ....shared.settings import FieldType, SettingField
from .field_base import BaseFieldWidget

# Shared dark-theme input styling
_INPUT_STYLE = """
    QLineEdit, QPlainTextEdit {
        background-color: #1e1e3f;
        color: #ffffff;
        border: 1px solid #2a2a4a;
        border-radius: 6px;
        padding: 6px 10px;
        font-size: 13px;
    }
    QLineEdit:focus, QPlainTextEdit:focus {
        border-color: #e94560;
    }
"""

_LIST_STYLE = """
    QListWidget {
        background-color: #1e1e3f;
        color: #ffffff;
        border: 1px solid #2a2a4a;
        border-radius: 6px;
        padding: 4px;
        font-size: 13px;
    }
    QListWidget::item {
        padding: 4px 8px;
        border-radius: 4px;
    }
    QListWidget::item:selected {
        background-color: #3a3a5a;
    }
    QListWidget::item:hover {
        background-color: #2a2a4a;
    }
"""

_BTN_STYLE = """
    QPushButton {
        background-color: #2a2a4a;
        color: #ffffff;
        border: 1px solid #3a3a5a;
        border-radius: 4px;
        padding: 4px 8px;
        font-size: 13px;
    }
    QPushButton:hover {
        background-color: #3a3a5a;
    }
    QPushButton:pressed {
        background-color: #4a4a6a;
    }
"""

_SLIDER_STYLE = """
    QSlider::groove:horizontal {
        height: 6px;
        background: #2a2a4a;
        border-radius: 3px;
    }
    QSlider::handle:horizontal {
        background: #e94560;
        width: 16px;
        height: 16px;
        margin: -5px 0;
        border-radius: 8px;
    }
    QSlider::sub-page:horizontal {
        background: #e94560;
        border-radius: 3px;
    }
"""

_DATETIME_STYLE = """
    QDateEdit, QTimeEdit, QDateTimeEdit {
        background-color: #1e1e3f;
        color: #ffffff;
        border: 1px solid #2a2a4a;
        border-radius: 6px;
        padding: 6px 10px;
        font-size: 13px;
    }
    QDateEdit:focus, QTimeEdit:focus, QDateTimeEdit:focus {
        border-color: #e94560;
    }
    QDateEdit::drop-down, QTimeEdit::drop-down, QDateTimeEdit::drop-down {
        border: none;
        padding-right: 8px;
    }
    QCalendarWidget {
        background-color: #1e1e3f;
        color: #ffffff;
    }
"""


class MultilineFieldWidget(BaseFieldWidget):
    """Multi-line text input (QPlainTextEdit)."""

    def _build_input(self) -> None:
        self._text_edit = QPlainTextEdit()
        self._text_edit.setPlaceholderText(self.field.placeholder or "")
        self._text_edit.setMaximumHeight(100)
        self._text_edit.setStyleSheet(_INPUT_STYLE)
        self._text_edit.textChanged.connect(self._on_value_changed)
        self._input_layout.addWidget(self._text_edit)

    def get_value(self) -> str:
        return self._text_edit.toPlainText()

    def set_value(self, value: Any) -> None:
        self._text_edit.setPlainText(str(value) if value is not None else "")


class ActionFieldWidget(BaseFieldWidget):
    """Action button field (QPushButton).

    Triggers an action handler when clicked.
    """

    def __init__(
        self,
        field: SettingField,
        current_value: Any = None,
        parent: Optional[QWidget] = None,
        action_handler: Optional[Callable[[], None]] = None,
    ):
        self._action_handler = action_handler
        super().__init__(field, current_value, parent)

    def _build_input(self) -> None:
        self._button = QPushButton(self.field.label)
        self._button.setStyleSheet(_BTN_STYLE)
        self._button.clicked.connect(self._on_action_clicked)
        self._input_layout.addWidget(self._button)

        # Hide the label since button has its own text
        self._label.setVisible(False)

    def _on_action_clicked(self) -> None:
        if self._action_handler:
            self._action_handler()

    def get_value(self) -> None:
        return None

    def set_value(self, value: Any) -> None:
        pass

    def set_action_handler(self, handler: Callable[[], None]) -> None:
        """Set the action handler callback.

        Args:
            handler: Callable to invoke on button click.
        """
        self._action_handler = handler


class ListFieldWidget(BaseFieldWidget):
    """Editable list field (QListWidget with add/remove)."""

    def _build_input(self) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        # List widget
        self._list = QListWidget()
        self._list.setMaximumHeight(120)
        self._list.setStyleSheet(_LIST_STYLE)
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.model().rowsMoved.connect(self._on_value_changed)
        layout.addWidget(self._list)

        # Buttons
        btn_layout = QHBoxLayout()
        self._add_btn = QPushButton("+")
        self._add_btn.setFixedWidth(30)
        self._add_btn.setStyleSheet(_BTN_STYLE)
        self._add_btn.clicked.connect(self._on_add_clicked)
        self._remove_btn = QPushButton("−")
        self._remove_btn.setFixedWidth(30)
        self._remove_btn.setStyleSheet(_BTN_STYLE)
        self._remove_btn.clicked.connect(self._on_remove_clicked)
        btn_layout.addWidget(self._add_btn)
        btn_layout.addWidget(self._remove_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._input_layout.addWidget(container)

    def get_value(self) -> List[str]:
        items = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item:
                items.append(item.text())
        return items

    def set_value(self, value: Any) -> None:
        self._list.clear()
        if isinstance(value, list):
            for item in value:
                self._list.addItem(str(item))
        elif value:
            self._list.addItem(str(value))

    def _on_add_clicked(self) -> None:
        """Add empty editable item."""
        item = QListWidgetItem("")
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self._list.addItem(item)
        self._list.editItem(item)
        self._on_value_changed()

    def _on_remove_clicked(self) -> None:
        """Remove selected item."""
        current = self._list.currentRow()
        if current >= 0:
            self._list.takeItem(current)
            self._on_value_changed()


class ProviderOrderWidget(BaseFieldWidget):
    """Provider ordering with drag-drop and sub-settings.

    For PROVIDER_SELECT fields that control backend order.
    """

    def __init__(
        self,
        field: SettingField,
        current_value: Any = None,
        parent: Optional[QWidget] = None,
        available_providers: Optional[List[str]] = None,
    ):
        self._available_providers = available_providers or []
        super().__init__(field, current_value, parent)

    def _build_input(self) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        # List with drag-drop
        self._list = QListWidget()
        self._list.setMaximumHeight(100)
        self._list.setStyleSheet(_LIST_STYLE)
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.model().rowsMoved.connect(self._on_value_changed)
        layout.addWidget(self._list)

        # Buttons
        btn_layout = QHBoxLayout()
        for text, handler in [
            ("↑", self._move_up),
            ("↓", self._move_down),
            ("+", self._on_add_clicked),
            ("−", self._on_remove_clicked),
        ]:
            btn = QPushButton(text)
            btn.setFixedWidth(30)
            btn.setStyleSheet(_BTN_STYLE)
            btn.clicked.connect(handler)
            btn_layout.addWidget(btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._input_layout.addWidget(container)

    def get_value(self) -> List[str]:
        items = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item:
                items.append(item.text())
        return items

    def set_value(self, value: Any) -> None:
        self._list.clear()
        if isinstance(value, list):
            for item in value:
                self._list.addItem(str(item))
        elif isinstance(value, str):
            for item in value.split(","):
                item = item.strip()
                if item:
                    self._list.addItem(item)

    def set_available_providers(self, providers: List[str]) -> None:
        """Set available providers for add menu.

        Args:
            providers: List of provider names.
        """
        self._available_providers = providers

    def set_provider_health(
        self, health_status: Dict[str, tuple[bool, str | None]]
    ) -> None:
        """Set health status for providers and update styling.

        Args:
            health_status: Dict mapping provider name to (is_healthy, error_msg).
        """
        self._health_status = health_status
        self._update_health_display()

    def _update_health_display(self) -> None:
        """Update widget styling and message based on health status."""
        if not hasattr(self, "_health_status"):
            return

        unhealthy = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if not item:
                continue
            name = item.text()
            if name in self._health_status:
                is_healthy, error = self._health_status[name]
                if not is_healthy:
                    unhealthy.append((name, error))
                    item.setToolTip(error or "Backend unavailable")
                else:
                    item.setToolTip("")

        if unhealthy:
            if len(unhealthy) == 1:
                name, error = unhealthy[0]
                msg = f"'{name}' unavailable: {error}"
            else:
                names = ", ".join(f"'{n}'" for n, _ in unhealthy)
                msg = f"Unavailable backends: {names}"
            self.set_warning(msg)
        else:
            self.clear_warning()

    def _move_up(self) -> None:
        row = self._list.currentRow()
        if row > 0:
            item = self._list.takeItem(row)
            self._list.insertItem(row - 1, item)
            self._list.setCurrentRow(row - 1)
            self._on_value_changed()

    def _move_down(self) -> None:
        row = self._list.currentRow()
        if row < self._list.count() - 1:
            item = self._list.takeItem(row)
            self._list.insertItem(row + 1, item)
            self._list.setCurrentRow(row + 1)
            self._on_value_changed()

    def _on_add_clicked(self) -> None:
        """Add a provider from available list."""
        current = self.get_value()
        available = [p for p in self._available_providers if p not in current]
        if available:
            item, ok = QInputDialog.getItem(
                self, "Add Provider", "Select provider:", available, 0, False
            )
            if ok and item:
                self._list.addItem(item)
                self._on_value_changed()

    def _on_remove_clicked(self) -> None:
        """Remove selected provider."""
        current = self._list.currentRow()
        if current >= 0:
            self._list.takeItem(current)
            self._on_value_changed()


class PathFieldWidget(BaseFieldWidget):
    """File or directory path picker."""

    def _build_input(self) -> None:
        self._line_edit = QLineEdit()
        self._line_edit.setPlaceholderText(
            "Select file..."
            if self.field.type == FieldType.FILE_PATH
            else "Select directory..."
        )
        self._line_edit.setStyleSheet(_INPUT_STYLE)
        self._line_edit.textChanged.connect(self._on_value_changed)

        self._browse_btn = QPushButton("Browse...")
        self._browse_btn.setStyleSheet(_BTN_STYLE)
        self._browse_btn.clicked.connect(self._on_browse)

        self._input_layout.addWidget(self._line_edit, stretch=1)
        self._input_layout.addWidget(self._browse_btn)

    def get_value(self) -> str:
        return self._line_edit.text()

    def set_value(self, value: Any) -> None:
        self._line_edit.setText(str(value) if value else "")

    def _on_browse(self) -> None:
        """Open file/directory dialog."""
        if self.field.type == FieldType.FILE_PATH:
            file_filter = (
                self.field.metadata.get("filter", "All Files (*)")
                if self.field.metadata
                else "All Files (*)"
            )
            path, _ = QFileDialog.getOpenFileName(self, "Select File", "", file_filter)
        else:
            path = QFileDialog.getExistingDirectory(self, "Select Directory")

        if path:
            self._line_edit.setText(path)


class ColorFieldWidget(BaseFieldWidget):
    """Color picker with preview button."""

    def _build_input(self) -> None:
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(32, 32)
        self._color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._color_btn.clicked.connect(self._on_pick_color)

        self._hex_label = QLabel("#000000")
        self._hex_label.setMinimumWidth(70)
        self._hex_label.setStyleSheet("color: #a0a0a0; font-size: 13px;")

        self._current_color = QColor("#000000")

        self._input_layout.addWidget(self._color_btn)
        self._input_layout.addWidget(self._hex_label)
        self._input_layout.addStretch()

    def get_value(self) -> str:
        return self._current_color.name()

    def set_value(self, value: Any) -> None:
        if value:
            self._current_color = QColor(str(value))
        else:
            self._current_color = QColor("#000000")
        self._update_display()

    def _on_pick_color(self) -> None:
        color = QColorDialog.getColor(self._current_color, self, "Select Color")
        if color.isValid():
            self._current_color = color
            self._update_display()
            self._on_value_changed()

    def _update_display(self) -> None:
        """Update button background and hex label."""
        hex_name = self._current_color.name()
        self._color_btn.setStyleSheet(
            f"background-color: {hex_name}; border: 1px solid #3a3a5a; border-radius: 6px;"
        )
        self._hex_label.setText(hex_name)


class SliderFieldWidget(BaseFieldWidget):
    """Visual slider for numeric range."""

    def _build_input(self) -> None:
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setStyleSheet(_SLIDER_STYLE)

        # Set range
        min_val = int(self.field.min_value or 0)
        max_val = int(self.field.max_value or 100)
        self._slider.setMinimum(min_val)
        self._slider.setMaximum(max_val)
        self._slider.valueChanged.connect(self._on_slider_changed)

        self._value_label = QLabel()
        self._value_label.setMinimumWidth(40)
        self._value_label.setStyleSheet("color: #a0a0a0; font-size: 13px;")

        self._input_layout.addWidget(self._slider, stretch=1)
        self._input_layout.addWidget(self._value_label)

    def get_value(self) -> int:
        return self._slider.value()

    def set_value(self, value: Any) -> None:
        if value is not None:
            try:
                self._slider.setValue(int(value))
            except (ValueError, TypeError):
                pass
        self._value_label.setText(str(self._slider.value()))

    def _on_slider_changed(self, value: int) -> None:
        self._value_label.setText(str(value))
        self._on_value_changed()


class DateTimeFieldWidget(BaseFieldWidget):
    """Date, time, or datetime picker."""

    def _build_input(self) -> None:
        if self.field.type == FieldType.DATE:
            self._picker = QDateEdit()
            self._picker.setCalendarPopup(True)
            self._picker.dateChanged.connect(self._on_value_changed)
        elif self.field.type == FieldType.TIME:
            self._picker = QTimeEdit()
            self._picker.timeChanged.connect(self._on_value_changed)
        else:  # DATETIME
            self._picker = QDateTimeEdit()
            self._picker.setCalendarPopup(True)
            self._picker.dateTimeChanged.connect(self._on_value_changed)

        self._picker.setStyleSheet(_DATETIME_STYLE)
        self._input_layout.addWidget(self._picker)

    def get_value(self) -> str:
        if self.field.type == FieldType.DATE:
            return self._picker.date().toString(Qt.DateFormat.ISODate)
        elif self.field.type == FieldType.TIME:
            return self._picker.time().toString("HH:mm")
        else:
            return self._picker.dateTime().toString(Qt.DateFormat.ISODate)

    def set_value(self, value: Any) -> None:
        if not value:
            return
        try:
            if self.field.type == FieldType.DATE:
                self._picker.setDate(QDate.fromString(str(value), Qt.DateFormat.ISODate))
            elif self.field.type == FieldType.TIME:
                self._picker.setTime(QTime.fromString(str(value), "HH:mm"))
            else:
                self._picker.setDateTime(
                    QDateTime.fromString(str(value), Qt.DateFormat.ISODate)
                )
        except Exception:
            pass
