"""Settings dialog for configuration."""

from typing import Optional
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QLineEdit, QComboBox, QCheckBox, QPushButton,
    QFormLayout, QGroupBox, QMessageBox, QFileDialog
)
from PySide6.QtCore import Qt, Signal

from .theme import Theme, THEMES, get_stylesheet, DARK_THEME
from ..config import Settings


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
        
        layout.addStretch()
        
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
            "or use the /auth/register API endpoint."
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
        self._hub_token.setText(self.settings.hub.token or "")
        
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
        import asyncio
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
        
        # Run async test
        try:
            loop = asyncio.get_event_loop()
            success, message = loop.run_until_complete(test())
        except RuntimeError:
            # No event loop - create one
            success, message = asyncio.run(test())
        
        if success:
            QMessageBox.information(self, "Test Connection", f"✓ {message}")
        else:
            QMessageBox.warning(self, "Test Connection", f"✗ Connection failed:\n{message}")
    
    def _on_save(self):
        """Save settings and close dialog."""
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
        }
        
        self.settings_changed.emit(self._changes)
        self.accept()
    
    def get_changes(self) -> dict:
        """Get the settings changes."""
        return self._changes

