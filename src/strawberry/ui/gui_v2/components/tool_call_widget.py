"""Tool call widget with expandable details."""

import json
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..utils.icons import Icons


class ToolCallWidget(QFrame):
    """Expandable tool call display widget.

    Shows a clickable header with tool name and status, with an expandable
    details section showing arguments, result, and execution time.

    This widget is designed to blend seamlessly into the message flow,
    with minimal visual separation (subtle background tint, no nested borders).

    Signals:
        toggled: Emitted when expanded state changes (bool: expanded)
        height_changed: Emitted when widget height changes

    Visual States:
        - Collapsed: Single line with [▶] toggle, tool name, and status icon
        - Expanded: Header + indented details (args, result, duration)
        - Pending: Shows ⏳ spinner instead of result
        - Error: Shows ❌ with error message
    """

    toggled = Signal(bool)
    height_changed = Signal(int)

    def __init__(
        self,
        tool_name: str,
        arguments: Optional[dict] = None,
        result: Optional[str] = None,
        error: Optional[str] = None,
        duration_ms: Optional[int] = None,
        expanded: bool = False,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._tool_name = tool_name
        self._arguments = arguments or {}
        self._result = result
        self._error = error
        self._duration_ms = duration_ms
        self._expanded = expanded
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Initialize the UI layout."""
        self.setObjectName("ToolCallWidget")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(0)

        # Header row (always visible)
        self._header = QWidget()
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        # Toggle indicator [▶] or [▼]
        self._toggle_label = QLabel()
        self._toggle_label.setObjectName("ToggleLabel")
        self._toggle_label.setFixedWidth(16)
        self._update_toggle_icon()
        header_layout.addWidget(self._toggle_label)

        # Tool icon and name
        self._name_label = QLabel(f"{Icons.TOOL} {self._tool_name}")
        self._name_label.setObjectName("ToolName")
        header_layout.addWidget(self._name_label, 1)

        # Status indicator (pending/success/error)
        self._status_label = QLabel()
        self._status_label.setObjectName("StatusLabel")
        self._update_status_icon()
        header_layout.addWidget(self._status_label)

        layout.addWidget(self._header)

        # Details section (collapsible)
        self._details = QWidget()
        self._details.setObjectName("ToolDetails")
        details_layout = QVBoxLayout(self._details)
        details_layout.setContentsMargins(24, 4, 0, 4)  # Indent under toggle
        details_layout.setSpacing(2)

        # Arguments
        self._args_label = QLabel()
        self._args_label.setObjectName("ToolDetails")
        self._args_label.setWordWrap(True)
        self._args_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._update_args_label()
        details_layout.addWidget(self._args_label)

        # Result or error
        self._result_label = QLabel()
        self._result_label.setObjectName("ToolDetails")
        self._result_label.setWordWrap(True)
        self._result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._update_result_label()
        details_layout.addWidget(self._result_label)

        # Duration (only shown if available)
        self._duration_label = QLabel()
        self._duration_label.setObjectName("ToolDetails")
        self._update_duration_label()
        details_layout.addWidget(self._duration_label)

        layout.addWidget(self._details)

        # Set initial visibility
        self._details.setVisible(self._expanded)

    def _update_toggle_icon(self) -> None:
        """Update the toggle indicator."""
        icon = Icons.COLLAPSE if self._expanded else Icons.EXPAND
        self._toggle_label.setText(icon)

    def _update_status_icon(self) -> None:
        """Update the status indicator."""
        if self._error:
            self._status_label.setText(Icons.ERROR)
            self._status_label.setToolTip(f"Error: {self._error}")
        elif self._result is not None:
            self._status_label.setText(Icons.SUCCESS)
            self._status_label.setToolTip("Completed successfully")
        else:
            self._status_label.setText(Icons.PENDING)
            self._status_label.setToolTip("Pending...")

    def _update_args_label(self) -> None:
        """Update the arguments display."""
        if self._arguments:
            try:
                args_str = json.dumps(self._arguments, indent=2)
            except (TypeError, ValueError):
                args_str = str(self._arguments)
            self._args_label.setText(f"Args: {args_str}")
            self._args_label.show()
        else:
            self._args_label.hide()

    def _update_result_label(self) -> None:
        """Update the result/error display."""
        if self._error:
            self._result_label.setText(f"{Icons.ERROR} Error: {self._error}")
            self._result_label.setProperty("error", True)
        elif self._result is not None:
            # Truncate long results for display
            display_result = self._result
            if len(display_result) > 500:
                display_result = display_result[:500] + "..."
            self._result_label.setText(f"Result: {display_result}")
            self._result_label.setProperty("error", False)
        else:
            self._result_label.setText(f"{Icons.PENDING} Pending...")
            self._result_label.setProperty("error", False)

    def _update_duration_label(self) -> None:
        """Update the duration display."""
        if self._duration_ms is not None:
            seconds = self._duration_ms / 1000
            self._duration_label.setText(f"Duration: {seconds:.2f}s")
            self._duration_label.show()
        else:
            self._duration_label.hide()

    def mousePressEvent(self, event) -> None:
        """Toggle expanded state on click."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle()
            event.accept()
        else:
            super().mousePressEvent(event)

    def toggle(self) -> None:
        """Toggle the expanded state."""
        self._expanded = not self._expanded
        self._update_toggle_icon()
        self._details.setVisible(self._expanded)
        self.toggled.emit(self._expanded)
        self.height_changed.emit(self.sizeHint().height())

    def set_expanded(self, expanded: bool) -> None:
        """Set the expanded state.

        Args:
            expanded: Whether to expand or collapse
        """
        if self._expanded != expanded:
            self.toggle()

    def set_result(self, result: str, duration_ms: Optional[int] = None) -> None:
        """Update the tool call result.

        Args:
            result: The result string
            duration_ms: Optional execution time in milliseconds
        """
        self._result = result
        self._error = None
        if duration_ms is not None:
            self._duration_ms = duration_ms

        self._update_status_icon()
        self._update_result_label()
        self._update_duration_label()
        self.height_changed.emit(self.sizeHint().height())

    def set_error(self, error: str) -> None:
        """Set error state.

        Args:
            error: The error message
        """
        self._error = error
        self._result = None

        self._update_status_icon()
        self._update_result_label()
        self.height_changed.emit(self.sizeHint().height())

    @property
    def tool_name(self) -> str:
        """Get the tool name."""
        return self._tool_name

    @property
    def is_pending(self) -> bool:
        """Check if the tool call is still pending."""
        return self._result is None and self._error is None

    @property
    def is_expanded(self) -> bool:
        """Check if the widget is expanded."""
        return self._expanded
