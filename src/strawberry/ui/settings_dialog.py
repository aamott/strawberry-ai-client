"""Settings dialog for configuration."""

import asyncio
import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import Settings
from .theme import DARK_THEME, Theme, get_stylesheet


class SettingsDialog(QDialog):
    """Settings configuration dialog.

    Allows users to configure:
    - Device name
    - Hub connection (URL, token)
    - UI theme
    - Skills folder

    Signals:
        settings_changed: Emitted when settings are saved
    """

    settings_changed = Signal(dict)

    def __init__(
        self,
        settings: Settings,
        theme: Optional[Theme] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        self.settings = settings
        self._theme = theme or DARK_THEME
        self._changes: dict = {}

        self._setup_ui()
        self._load_current_settings()
        self._apply_theme()

    def _setup_ui(self):
        """Set up the dialog UI."""
        self.setWindowTitle("Settings")
        self.setMinimumSize(500, 400)
        self.resize(550, 450)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # Tab widget
        tabs = QTabWidget()

        # General tab
        general_tab = self._create_general_tab()
        tabs.addTab(general_tab, "General")

        # Hub tab
        hub_tab = self._create_hub_tab()
        tabs.addTab(hub_tab, "Hub Connection")

        # Appearance tab
        appearance_tab = self._create_appearance_tab()
        tabs.addTab(appearance_tab, "Appearance")

        # Environment tab
        env_tab = self._create_env_tab()
        tabs.addTab(env_tab, "Environment")

        layout.addWidget(tabs)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setProperty("secondary", True)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._on_save)
        button_layout.addWidget(save_btn)

        layout.addLayout(button_layout)

    def _create_general_tab(self) -> QWidget:
        """Create the general settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)

        # Device group
        device_group = QGroupBox("Device")
        device_layout = QFormLayout(device_group)

        self._device_name = QLineEdit()
        self._device_name.setPlaceholderText("My Strawberry Spoke")
        device_layout.addRow("Device Name:", self._device_name)

        self._device_id = QLineEdit()
        self._device_id.setReadOnly(True)
        self._device_id.setProperty("muted", True)
        device_layout.addRow("Device ID:", self._device_id)

        layout.addWidget(device_group)

        # Skills group
        skills_group = QGroupBox("Skills")
        skills_layout = QFormLayout(skills_group)

        skills_path_layout = QHBoxLayout()
        self._skills_path = QLineEdit()
        self._skills_path.setPlaceholderText("./skills")
        skills_path_layout.addWidget(self._skills_path)

        browse_btn = QPushButton("Browse...")
        browse_btn.setProperty("secondary", True)
        browse_btn.clicked.connect(self._browse_skills_path)
        skills_path_layout.addWidget(browse_btn)

        skills_layout.addRow("Skills Folder:", skills_path_layout)

        layout.addWidget(skills_group)

        # TensorZero config
        tz_group = QGroupBox("TensorZero")
        tz_layout = QHBoxLayout(tz_group)

        tz_path = Path("config") / "tensorzero.toml"
        self._tensorzero_path_label = QLabel(str(tz_path))
        self._tensorzero_path_label.setProperty("muted", True)
        tz_layout.addWidget(self._tensorzero_path_label, 1)

        open_tz_btn = QPushButton("Open tensorzero.toml")
        open_tz_btn.setProperty("secondary", True)
        open_tz_btn.clicked.connect(self._open_tensorzero_toml)
        tz_layout.addWidget(open_tz_btn)

        layout.addWidget(tz_group)

        layout.addStretch()

        return tab

    def _open_tensorzero_toml(self):
        tz_path = (Path("config") / "tensorzero.toml").resolve()

        if not tz_path.exists():
            choice = QMessageBox.question(
                self,
                "Create tensorzero.toml",
                "config/tensorzero.toml does not exist. Create a minimal template now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if choice != QMessageBox.StandardButton.Yes:
                return

            tz_path.parent.mkdir(parents=True, exist_ok=True)
            tz_path.write_text(
                "\n".join(
                    [
                        "[gateway]",
                        "",
                        "[functions.chat]",
                        'type = "chat"',
                        "",
                        "[functions.chat.variants.default]",
                        'type = "chat_completion"',
                        'model = "openai::gpt-4o-mini-2024-07-18"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(tz_path)))

    def _create_env_tab(self) -> QWidget:
        """Create the environment variable settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)

        # Common secrets / keys
        secrets_group = QGroupBox("Secrets")
        secrets_layout = QFormLayout(secrets_group)

        self._show_secrets = QCheckBox("Show secret values")
        secrets_layout.addRow("", self._show_secrets)

        def _secret_line_edit(placeholder: str) -> QLineEdit:
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            return edit

        self._env_picovoice_api_key = _secret_line_edit("PICOVOICE_API_KEY")
        secrets_layout.addRow("PICOVOICE_API_KEY:", self._env_picovoice_api_key)

        self._env_openai_api_key = _secret_line_edit("OPENAI_API_KEY")
        secrets_layout.addRow("OPENAI_API_KEY:", self._env_openai_api_key)

        self._env_anthropic_api_key = _secret_line_edit("ANTHROPIC_API_KEY")
        secrets_layout.addRow("ANTHROPIC_API_KEY:", self._env_anthropic_api_key)

        self._env_google_api_key = _secret_line_edit("GOOGLE_API_KEY")
        secrets_layout.addRow("GOOGLE_API_KEY:", self._env_google_api_key)

        self._env_google_search_engine_id = QLineEdit()
        self._env_google_search_engine_id.setPlaceholderText("GOOGLE_SEARCH_ENGINE_ID")
        secrets_layout.addRow("GOOGLE_SEARCH_ENGINE_ID:", self._env_google_search_engine_id)

        self._env_news_api_key = _secret_line_edit("NEWS_API_KEY")
        secrets_layout.addRow("NEWS_API_KEY:", self._env_news_api_key)

        self._env_weather_api_key = _secret_line_edit("WEATHER_API_KEY")
        secrets_layout.addRow("WEATHER_API_KEY:", self._env_weather_api_key)

        def _toggle_secrets(checked: bool):
            mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            self._env_picovoice_api_key.setEchoMode(mode)
            self._env_openai_api_key.setEchoMode(mode)
            self._env_anthropic_api_key.setEchoMode(mode)
            self._env_google_api_key.setEchoMode(mode)
            self._env_news_api_key.setEchoMode(mode)
            self._env_weather_api_key.setEchoMode(mode)

        self._show_secrets.toggled.connect(_toggle_secrets)

        layout.addWidget(secrets_group)

        # Advanced environment variables
        advanced_group = QGroupBox("Other Environment Variables")
        advanced_layout = QVBoxLayout(advanced_group)

        self._env_table = QTableWidget(0, 2)
        self._env_table.setHorizontalHeaderLabels(["Key", "Value"])
        self._env_table.horizontalHeader().setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        self._env_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._env_table.verticalHeader().setVisible(False)
        self._env_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._env_table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.EditKeyPressed
        )
        advanced_layout.addWidget(self._env_table)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        add_btn = QPushButton("Add")
        add_btn.setProperty("secondary", True)
        btn_row.addWidget(add_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.setProperty("secondary", True)
        btn_row.addWidget(remove_btn)

        advanced_layout.addLayout(btn_row)
        layout.addWidget(advanced_group)

        def _add_row(key: str = "", value: str = ""):
            row = self._env_table.rowCount()
            self._env_table.insertRow(row)
            self._env_table.setItem(row, 0, QTableWidgetItem(key))
            self._env_table.setItem(row, 1, QTableWidgetItem(value))

        def _remove_selected_rows():
            rows = sorted({i.row() for i in self._env_table.selectedIndexes()}, reverse=True)
            for r in rows:
                self._env_table.removeRow(r)

        add_btn.clicked.connect(lambda: _add_row())
        remove_btn.clicked.connect(_remove_selected_rows)

        # Seed the UI from current process environment
        self._env_original = {
            "PICOVOICE_API_KEY": os.environ.get("PICOVOICE_API_KEY", ""),
            "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
            "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
            "GOOGLE_API_KEY": os.environ.get("GOOGLE_API_KEY", ""),
            "GOOGLE_SEARCH_ENGINE_ID": os.environ.get("GOOGLE_SEARCH_ENGINE_ID", ""),
            "NEWS_API_KEY": os.environ.get("NEWS_API_KEY", ""),
            "WEATHER_API_KEY": os.environ.get("WEATHER_API_KEY", ""),
        }

        self._env_picovoice_api_key.setText(self._env_original["PICOVOICE_API_KEY"])
        self._env_openai_api_key.setText(self._env_original["OPENAI_API_KEY"])
        self._env_anthropic_api_key.setText(self._env_original["ANTHROPIC_API_KEY"])
        self._env_google_api_key.setText(self._env_original["GOOGLE_API_KEY"])
        self._env_google_search_engine_id.setText(self._env_original["GOOGLE_SEARCH_ENGINE_ID"])
        self._env_news_api_key.setText(self._env_original["NEWS_API_KEY"])
        self._env_weather_api_key.setText(self._env_original["WEATHER_API_KEY"])

        # Don't auto-import the entire environment. Start empty and let the user add.
        return tab

    def _create_hub_tab(self) -> QWidget:
        """Create the Hub connection settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)

        # Connection group
        conn_group = QGroupBox("Hub Server")
        conn_layout = QFormLayout(conn_group)

        self._hub_url = QLineEdit()
        self._hub_url.setPlaceholderText("http://localhost:8000")
        conn_layout.addRow("Hub URL:", self._hub_url)

        self._hub_token = QLineEdit()
        self._hub_token.setPlaceholderText("Enter your Hub access token")
        self._hub_token.setEchoMode(QLineEdit.EchoMode.Password)
        conn_layout.addRow("Access Token:", self._hub_token)

        # Show/hide token button
        show_token_layout = QHBoxLayout()
        show_token_layout.addStretch()
        self._show_token_btn = QPushButton("Show Token")
        self._show_token_btn.setProperty("secondary", True)
        self._show_token_btn.setCheckable(True)
        self._show_token_btn.toggled.connect(self._toggle_token_visibility)
        show_token_layout.addWidget(self._show_token_btn)
        conn_layout.addRow("", show_token_layout)

        layout.addWidget(conn_group)

        # Test connection button
        test_layout = QHBoxLayout()
        test_layout.addStretch()
        test_btn = QPushButton("Test Connection")
        test_btn.clicked.connect(self._test_connection)
        test_layout.addWidget(test_btn)
        layout.addLayout(test_layout)

        # Info
        info_label = QLabel(
            "To get a Hub token, register your device at the Hub web interface "
            "and create a device token (POST /api/devices/token)."
        )
        info_label.setWordWrap(True)
        info_label.setProperty("muted", True)
        layout.addWidget(info_label)

        layout.addStretch()

        return tab

    def _create_appearance_tab(self) -> QWidget:
        """Create the appearance settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)

        # Theme group
        theme_group = QGroupBox("Theme")
        theme_layout = QFormLayout(theme_group)

        self._theme_combo = QComboBox()
        self._theme_combo.addItem("Dark", "dark")
        self._theme_combo.addItem("Light", "light")
        self._theme_combo.addItem("System", "system")
        theme_layout.addRow("Color Theme:", self._theme_combo)

        layout.addWidget(theme_group)

        # Behavior group
        behavior_group = QGroupBox("Behavior")
        behavior_layout = QVBoxLayout(behavior_group)

        self._start_minimized = QCheckBox("Start minimized to system tray")
        behavior_layout.addWidget(self._start_minimized)

        self._show_waveform = QCheckBox("Show waveform during voice recording")
        behavior_layout.addWidget(self._show_waveform)

        layout.addWidget(behavior_group)

        layout.addStretch()

        return tab

    def _load_current_settings(self):
        """Load current settings into the form."""
        # Device
        self._device_name.setText(self.settings.device.name)
        self._device_id.setText(self.settings.device.id)

        # Skills
        self._skills_path.setText(self.settings.skills.path)

        # Hub
        self._hub_url.setText(self.settings.hub.url)
        self._hub_token.setText(
            os.environ.get("HUB_DEVICE_TOKEN", "")
            or os.environ.get("HUB_TOKEN", "")
            or (self.settings.hub.token or "")
        )

        # Appearance
        index = self._theme_combo.findData(self.settings.ui.theme)
        if index >= 0:
            self._theme_combo.setCurrentIndex(index)

        self._start_minimized.setChecked(self.settings.ui.start_minimized)
        self._show_waveform.setChecked(self.settings.ui.show_waveform)

    def _apply_theme(self):
        """Apply the current theme to the dialog."""
        self.setStyleSheet(get_stylesheet(self._theme))

    def _browse_skills_path(self):
        """Open file dialog to select skills folder."""
        path = QFileDialog.getExistingDirectory(
            self,
            "Select Skills Folder",
            self._skills_path.text() or ".",
        )
        if path:
            self._skills_path.setText(path)

    def _toggle_token_visibility(self, checked: bool):
        """Toggle token visibility."""
        if checked:
            self._hub_token.setEchoMode(QLineEdit.EchoMode.Normal)
            self._show_token_btn.setText("Hide Token")
        else:
            self._hub_token.setEchoMode(QLineEdit.EchoMode.Password)
            self._show_token_btn.setText("Show Token")

    def _test_connection(self):
        """Test Hub connection with current settings."""

        from ..hub import HubClient, HubConfig

        url = self._hub_url.text().strip()
        token = self._hub_token.text().strip()

        if not url:
            QMessageBox.warning(self, "Test Connection", "Please enter a Hub URL")
            return

        if not token:
            QMessageBox.warning(self, "Test Connection", "Please enter an access token")
            return

        # Test connection
        async def test():
            config = HubConfig(url=url, token=token, timeout=10.0)
            client = HubClient(config)
            try:
                healthy = await client.health()
                if healthy:
                    # Try to get device info
                    info = await client.get_device_info()
                    return True, f"Connected! Device: {info.get('name', 'Unknown')}"
                else:
                    return False, "Hub is not responding"
            except Exception as e:
                return False, str(e)
            finally:
                await client.close()

        async def run_and_show() -> None:
            success, message = await test()
            if success:
                QMessageBox.information(self, "Test Connection", f"✓ {message}")
            else:
                QMessageBox.warning(
                    self,
                    "Test Connection",
                    f"✗ Connection failed:\n{message}",
                )

        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(run_and_show())
            return

        # Fallback (no running loop)
        loop.run_until_complete(run_and_show())

    def _on_save(self):
        """Save settings and close dialog."""
        def _clean_env_value(text: str) -> Optional[str]:
            value = text.strip()
            if value == "":
                return None
            return value

        env_updates = {
            "HUB_DEVICE_TOKEN": _clean_env_value(self._hub_token.text()),
            # Backward compatibility: config/config.yaml may still reference ${HUB_TOKEN}
            "HUB_TOKEN": _clean_env_value(self._hub_token.text()),
            "PICOVOICE_API_KEY": _clean_env_value(self._env_picovoice_api_key.text()),
            "OPENAI_API_KEY": _clean_env_value(self._env_openai_api_key.text()),
            "ANTHROPIC_API_KEY": _clean_env_value(self._env_anthropic_api_key.text()),
            "GOOGLE_API_KEY": _clean_env_value(self._env_google_api_key.text()),
            "GOOGLE_SEARCH_ENGINE_ID": _clean_env_value(self._env_google_search_engine_id.text()),
            "NEWS_API_KEY": _clean_env_value(self._env_news_api_key.text()),
            "WEATHER_API_KEY": _clean_env_value(self._env_weather_api_key.text()),
        }

        # Additional env vars
        for row in range(self._env_table.rowCount()):
            key_item = self._env_table.item(row, 0)
            val_item = self._env_table.item(row, 1)
            key = key_item.text().strip() if key_item else ""
            if not key:
                continue
            value = val_item.text() if val_item else ""
            env_updates[key] = _clean_env_value(value)

        # Collect changes
        self._changes = {
            "device": {
                "name": self._device_name.text().strip() or "Strawberry Spoke",
            },
            "hub": {
                "url": self._hub_url.text().strip() or "http://localhost:8000",
                "token": self._hub_token.text().strip() or None,
            },
            "skills": {
                "path": self._skills_path.text().strip() or "./skills",
            },
            "ui": {
                "theme": self._theme_combo.currentData(),
                "start_minimized": self._start_minimized.isChecked(),
                "show_waveform": self._show_waveform.isChecked(),
            },
            "env": env_updates,
        }

        self.settings_changed.emit(self._changes)
        self.accept()

    def get_changes(self) -> dict:
        """Get the settings changes."""
        return self._changes

