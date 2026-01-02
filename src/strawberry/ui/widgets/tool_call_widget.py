"""Widget for displaying tool/skill calls in chat."""

from typing import Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..theme import Theme


class ToolCallWidget(QFrame):
    """Widget displaying a tool/skill call and its result.

    Shows:
    - Tool name and arguments
    - Execution status (running, success, error)
    - Result or error message
    - Expandable/collapsible details
    """

    def __init__(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        theme: Optional[Theme] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        self.tool_name = tool_name
        self.arguments = arguments
        self._theme = theme
        self._expanded = True
        self._status = "pending"  # pending, running, success, error
        self._result: Optional[str] = None

        self._setup_ui()
        self._apply_style()

    def _setup_ui(self):
        """Set up the widget UI."""
        self.setObjectName("toolCallWidget")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        # Header row
        header = QHBoxLayout()
        header.setSpacing(8)

        # Tool icon/indicator
        self._status_icon = QLabel("⚡")
        self._status_icon.setFixedWidth(20)
        header.addWidget(self._status_icon)

        # Tool name
        name_label = QLabel(f"<b>{self.tool_name}</b>")
        header.addWidget(name_label)

        header.addStretch()

        # Status label
        self._status_label = QLabel("Pending")
        self._status_label.setProperty("muted", True)
        header.addWidget(self._status_label)

        # Expand/collapse button
        self._expand_btn = QPushButton("▼")
        self._expand_btn.setFixedSize(24, 24)
        self._expand_btn.setProperty("secondary", True)
        self._expand_btn.clicked.connect(self._toggle_expand)
        header.addWidget(self._expand_btn)

        layout.addLayout(header)

        # Arguments summary (always visible)
        args_text = ", ".join(f"{k}={repr(v)}" for k, v in self.arguments.items())
        if len(args_text) > 60:
            args_text = args_text[:57] + "..."

        self._args_label = QLabel(args_text or "(no arguments)")
        self._args_label.setProperty("muted", True)
        args_font = QFont()
        args_font.setFamily("Consolas, Monaco, monospace")
        args_font.setPointSize(11)
        self._args_label.setFont(args_font)
        layout.addWidget(self._args_label)

        # Expandable details section
        self._details_frame = QFrame()
        self._details_frame.setVisible(True)
        details_layout = QVBoxLayout(self._details_frame)
        details_layout.setContentsMargins(0, 8, 0, 0)

        # Code / full arguments
        self._full_args = QLabel()
        self._full_args.setWordWrap(True)
        args_font = QFont()
        args_font.setFamily("Consolas, Monaco, monospace")
        args_font.setPointSize(11)
        self._full_args.setFont(args_font)
        self._full_args.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        details_layout.addWidget(self._full_args)

        # Output / error
        self._result_label = QLabel()
        self._result_label.setWordWrap(True)
        self._result_label.setFont(args_font)
        self._result_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        details_layout.addWidget(self._result_label)

        layout.addWidget(self._details_frame)

        # Initialize expanded content
        self._update_details_text()

    def _apply_style(self):
        """Apply theme-based styling."""
        if not self._theme:
            return

        # Base style
        bg = self._theme.bg_tertiary
        border = self._theme.border

        self.setStyleSheet(f"""
            QFrame#toolCallWidget {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
        """)

    def _toggle_expand(self):
        """Toggle expanded state."""
        self._expanded = not self._expanded
        self._details_frame.setVisible(self._expanded)
        self._expand_btn.setText("▼" if self._expanded else "▶")

        if self._expanded:
            self._update_details_text()

    def _update_details_text(self):
        code = self.arguments.get("code") if isinstance(self.arguments, dict) else None
        if code is not None:
            self._full_args.setText(f"Code:\n{code}")
            return

        args_lines = [f"  {k}: {repr(v)}" for k, v in self.arguments.items()]
        self._full_args.setText("Arguments:\n" + "\n".join(args_lines))

    def set_running(self):
        """Set status to running."""
        self._status = "running"
        self._status_icon.setText("⏳")
        self._status_label.setText("Running...")
        self._update_status_style()

    def set_success(self, result: Any):
        """Set status to success with result."""
        self._status = "success"
        self._result = str(result) if result is not None else "None"
        self._status_icon.setText("✓")
        self._status_label.setText("Success")
        self._result_label.setText(f"Output:\n{self._result}")
        self._update_status_style()

    def set_error(self, error: str):
        """Set status to error."""
        self._status = "error"
        self._result = error
        self._status_icon.setText("✗")
        self._status_label.setText("Error")
        self._result_label.setText(f"Error:\n{error}")
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

        self._status_icon.setStyleSheet(f"color: {color}; background: transparent;")
        self._status_label.setStyleSheet(f"color: {color}; background: transparent;")

