"""Qt widget for editing MCP server configurations.

This provides a structured editor for MCP servers instead of requiring users to
manually edit JSON/YAML.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from strawberry.mcp.config import MCPServerConfig


@dataclass
class _ValidationResult:
    ok: bool
    error: Optional[str] = None


class MCPServersWidget(QWidget):
    """Widget for editing a list of MCP server configurations.

    The underlying value is `list[dict[str, Any]]` compatible with
    `MCPServerConfig.from_dict`.

    Signals:
        value_changed(key, value): emitted when list changes.
    """

    value_changed = Signal(str, object)

    def __init__(
        self,
        *,
        key: str,
        value: Any,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._key = key
        self._servers: List[Dict[str, Any]] = self._coerce_value(value)

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        self._add_btn = QPushButton("Add")
        self._edit_btn = QPushButton("Edit")
        self._remove_btn = QPushButton("Remove")

        self._setup_ui()
        self._wire_events()
        self._refresh_list()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        help_label = QLabel(
            "Add MCP servers one at a time. Invalid servers will be highlighted and "
            "skipped at runtime."
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #666;")

        layout.addWidget(help_label)
        layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(self._edit_btn)
        btn_row.addWidget(self._remove_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _wire_events(self) -> None:
        self._add_btn.clicked.connect(self._on_add)
        self._edit_btn.clicked.connect(self._on_edit)
        self._remove_btn.clicked.connect(self._on_remove)
        self._list.itemSelectionChanged.connect(self._update_button_state)
        self._update_button_state()

    def _update_button_state(self) -> None:
        has_sel = self._list.currentRow() >= 0
        self._edit_btn.setEnabled(has_sel)
        self._remove_btn.setEnabled(has_sel)

    def _emit(self) -> None:
        self.value_changed.emit(self._key, list(self._servers))

    def _on_add(self) -> None:
        dialog = _MCPServerDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        server_dict = dialog.get_value()
        self._servers.append(server_dict)
        self._refresh_list()
        self._emit()

    def _on_edit(self) -> None:
        idx = self._list.currentRow()
        if idx < 0 or idx >= len(self._servers):
            return

        dialog = _MCPServerDialog(initial=self._servers[idx], parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._servers[idx] = dialog.get_value()
        self._refresh_list()
        self._emit()

    def _on_remove(self) -> None:
        idx = self._list.currentRow()
        if idx < 0 or idx >= len(self._servers):
            return

        reply = QMessageBox.question(
            self,
            "Remove MCP Server",
            "Remove selected MCP server?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._servers.pop(idx)
        self._refresh_list()
        self._emit()

    def _refresh_list(self) -> None:
        self._list.clear()

        for server in self._servers:
            name = str(server.get("name") or "(unnamed)")
            enabled = bool(server.get("enabled", True))
            validation = self._validate_server(server)

            label = f"{name}"
            if not enabled:
                label += " (disabled)"

            if not validation.ok:
                label += "  - INVALID"

            item = QListWidgetItem(label)
            if not validation.ok:
                item.setForeground(QColor("#b00020"))
                item.setToolTip(validation.error or "Invalid configuration")
            else:
                item.setToolTip(self._format_tooltip(server))

            self._list.addItem(item)

        self._update_button_state()

    def _validate_server(self, server: Dict[str, Any]) -> _ValidationResult:
        try:
            MCPServerConfig.from_dict(server)
            return _ValidationResult(ok=True)
        except Exception as e:  # noqa: BLE001
            return _ValidationResult(ok=False, error=str(e))

    def _format_tooltip(self, server: Dict[str, Any]) -> str:
        try:
            return json.dumps(server, indent=2, sort_keys=True)
        except Exception:  # noqa: BLE001
            return str(server)

    def _coerce_value(self, value: Any) -> List[Dict[str, Any]]:
        if value is None:
            return []

        if isinstance(value, list):
            return [v for v in value if isinstance(v, dict)]

        # The MULTILINE schema field can provide string values.
        if isinstance(value, str):
            try:
                parsed = json.loads(value) if value.strip() else []
                if isinstance(parsed, list):
                    return [v for v in parsed if isinstance(v, dict)]
            except json.JSONDecodeError:
                return []

        return []


class _MCPServerDialog(QDialog):
    """Dialog for adding/editing a single MCP server."""

    def __init__(
        self,
        initial: Optional[Dict[str, Any]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("MCP Server")
        self.setModal(True)
        self.resize(520, 300)

        self._name = QLineEdit()
        self._command = QLineEdit()
        self._args = QLineEdit()
        self._env = QLineEdit()
        self._transport = QLineEdit()
        self._url = QLineEdit()
        self._timeout = QSpinBox()
        self._timeout.setMinimum(1)
        self._timeout.setMaximum(3600)

        self._enabled = QPushButton("Enabled")
        self._enabled.setCheckable(True)

        self._setup_ui()
        self._apply_initial(initial or {})

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        box = QGroupBox("Server")
        form = QFormLayout(box)

        form.addRow(QLabel("Name:"), self._name)
        form.addRow(QLabel("Command:"), self._command)
        form.addRow(QLabel("Args (JSON list):"), self._args)
        form.addRow(QLabel("Env (JSON dict):"), self._env)
        form.addRow(QLabel("Transport (stdio|sse):"), self._transport)
        form.addRow(QLabel("URL (for sse):"), self._url)
        form.addRow(QLabel("Timeout (sec):"), self._timeout)
        form.addRow(QLabel(""), self._enabled)

        layout.addWidget(box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        hint = QLabel(
            "Tip: keep secrets in environment variables and reference them like ${MY_KEY} in Env."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666;")
        layout.addWidget(hint)

    def _apply_initial(self, initial: Dict[str, Any]) -> None:
        self._name.setText(str(initial.get("name") or ""))
        self._command.setText(str(initial.get("command") or ""))

        args = initial.get("args") or []
        env = initial.get("env") or {}

        self._args.setText(json.dumps(args))
        self._env.setText(json.dumps(env))

        self._transport.setText(str(initial.get("transport") or "stdio"))
        self._url.setText(str(initial.get("url") or ""))

        self._timeout.setValue(int(initial.get("timeout") or 30))
        self._enabled.setChecked(bool(initial.get("enabled", True)))

    def _parse_json(self, text: str, expected_type: type) -> Any:
        if not text.strip():
            return expected_type()
        value = json.loads(text)
        if not isinstance(value, expected_type):
            raise ValueError(f"Expected {expected_type.__name__}")
        return value

    def get_value(self) -> Dict[str, Any]:
        args = self._parse_json(self._args.text(), list)
        env = self._parse_json(self._env.text(), dict)

        value: Dict[str, Any] = {
            "name": self._name.text().strip(),
            "command": self._command.text().strip(),
            "args": args,
            "env": {str(k): str(v) for k, v in env.items()},
            "enabled": bool(self._enabled.isChecked()),
            "transport": (self._transport.text().strip() or "stdio"),
            "url": (self._url.text().strip() or None),
            "timeout": float(self._timeout.value()),
        }

        # Normalize: for stdio, url should be None
        if value["transport"] != "sse":
            value["url"] = None

        return value

    def _on_accept(self) -> None:
        try:
            cfg = MCPServerConfig.from_dict(self.get_value())
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Invalid MCP Server", str(e))
            return

        # Also ensure skill name is a valid identifier-ish
        if not cfg.skill_name.endswith("MCP"):
            QMessageBox.warning(self, "Invalid MCP Server", "Invalid server name")
            return

        self.accept()
