"""Widget for displaying tool/skill calls in chat."""

import json
from typing import Any, Dict, Optional

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..theme import Theme
from .code_block_widget import CodeBlockWidget
from .output_widget import OutputWidget


class ToolCallWidget(QFrame):
    """Compact, notebook-cell-style rendering of a tool call.

    Layout:
    - small header line: tool name + status
    - code cell: either the python_exec code, or JSON args for other tools
    - output cell: output or error
    """

    def __init__(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]],
        theme: Optional[Theme] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        self.tool_name = tool_name
        self.arguments: Dict[str, Any] = arguments or {}
        self._theme = theme
        self._status = "pending"  # pending, running, success, error
        self._result: Optional[str] = None

        self._setup_ui()
        self._apply_style()

    def _setup_ui(self):
        """Set up the widget UI."""
        self.setObjectName("toolCallWidget")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)

        self._title_label = QLabel(self.tool_name)
        title_font = QFont()
        title_font.setWeight(QFont.Weight.DemiBold)
        title_font.setPointSize(10)
        self._title_label.setFont(title_font)
        self._title_label.setProperty("muted", True)
        header.addWidget(self._title_label)

        header.addStretch()

        self._status_label = QLabel("Pending")
        self._status_label.setProperty("muted", True)
        status_font = QFont()
        status_font.setPointSize(10)
        self._status_label.setFont(status_font)
        header.addWidget(self._status_label)

        layout.addLayout(header)

        # Code cell
        self._code_widget = CodeBlockWidget(
            code=self._format_code_cell(),
            language=self._get_code_language(),
            theme=self._theme,
            parent=self,
        )
        layout.addWidget(self._code_widget)

        # Output cell (starts empty)
        self._output_widget = OutputWidget(
            content="",
            theme=self._theme,
            parent=self,
        )
        layout.addWidget(self._output_widget)

    def _apply_style(self):
        """Apply theme-based styling."""
        if not self._theme:
            return

        # Keep this inline/minimal (no card background/border)
        self.setStyleSheet("QFrame#toolCallWidget { background: transparent; border: none; }")

    def _get_code_language(self) -> str:
        if self.tool_name == "python_exec" and "code" in self.arguments:
            return "python"
        return "json"

    def _format_code_cell(self) -> str:
        if self.tool_name == "python_exec" and "code" in self.arguments:
            return str(self.arguments.get("code") or "")

        try:
            return json.dumps(self.arguments, indent=2, sort_keys=True)
        except TypeError:
            # Fallback if args contain non-JSON-serializable types
            return "\n".join(f"{k}: {repr(v)}" for k, v in self.arguments.items())

    def set_running(self):
        """Set status to running."""
        self._status = "running"
        self._status_label.setText("Running...")
        self._update_status_style()

    def set_success(self, result: Any):
        """Set status to success with result."""
        self._status = "success"
        self._result = str(result) if result is not None else "None"
        self._status_label.setText("Success")
        self._output_widget.set_content(self._result)
        self._update_status_style()

    def set_error(self, error: str):
        """Set status to error."""
        self._status = "error"
        self._result = error
        self._status_label.setText("Error")
        self._output_widget.set_content(f"Error: {error}")
        self._update_status_style()

    def _update_status_style(self):
        """Update styling based on status."""
        if not self._theme:
            return

        if self._status == "success":
            color = self._theme.success
        elif self._status == "error":
            color = self._theme.error
        elif self._status == "running":
            color = self._theme.warning
        else:
            color = self._theme.text_muted

        self._status_label.setStyleSheet(f"color: {color}; background: transparent;")

