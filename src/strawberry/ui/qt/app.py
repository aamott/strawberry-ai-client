"""Main application class with system tray support."""

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

try:
    import qasync
    HAS_QASYNC = True
except ImportError:
    HAS_QASYNC = False

from ...config import Settings, load_config
from ...shared.settings import SettingsManager
from ...utils.paths import get_project_root
from ...voice import VoiceConfig, VoiceCore
from .main_window import MainWindow


def create_strawberry_icon() -> QIcon:
    """Create a simple strawberry icon programmatically."""
    # Create a 64x64 pixmap
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Draw strawberry body (red circle)
    painter.setBrush(QColor("#ff6b6b"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(8, 16, 48, 44)

    # Draw stem (green)
    painter.setBrush(QColor("#4caf50"))
    painter.drawEllipse(24, 4, 16, 16)

    # Draw seeds (yellow dots)
    painter.setBrush(QColor("#ffeb3b"))
    seeds = [(20, 28), (36, 24), (28, 38), (44, 32), (24, 48), (40, 44)]
    for x, y in seeds:
        painter.drawEllipse(x, y, 4, 4)

    painter.end()

    return QIcon(pixmap)


class StrawberryApp:
    """Main application with system tray integration.

    Handles:
    - Application lifecycle
    - System tray icon and menu
    - Window management
    - Async event loop integration
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        start_minimized: bool = False,
    ):
        self.config_path = config_path
        self.start_minimized = start_minimized

        self._app: Optional[QApplication] = None
        self._window: Optional[MainWindow] = None
        self._tray: Optional[QSystemTrayIcon] = None
        self._settings: Optional[Settings] = None
        self._settings_manager: Optional[SettingsManager] = None
        self._voice_core: Optional[VoiceCore] = None

    def run(self) -> int:
        """Run the application.

        Returns:
            Exit code (0 for success)
        """
        # Create Qt application
        self._app = QApplication(sys.argv)
        self._app.setApplicationName("Strawberry AI")
        self._app.setOrganizationName("Strawberry")
        self._app.setQuitOnLastWindowClosed(False)  # Keep running in tray

        # Load legacy configuration (for backward compatibility)
        self._settings = load_config(self.config_path)

        # Create centralized SettingsManager
        # Config directory is at ai-pc-spoke/config/ for settings.yaml
        # But secrets (.env) should be at project root for compatibility
        project_root = get_project_root()
        config_dir = project_root / "config"
        self._settings_manager = SettingsManager(
            config_dir=config_dir,
            env_filename="../.env",  # Use root .env for secrets
        )

        # Create VoiceCore with SettingsManager
        # This registers voice_core namespace and all backend namespaces
        # so they appear in the settings dialog
        self._voice_core = VoiceCore(
            config=VoiceConfig(),
            settings_manager=self._settings_manager,
        )

        # Create main window with both old settings and new manager
        self._window = MainWindow(
            settings=self._settings,
            settings_manager=self._settings_manager,
            voice_core=self._voice_core,
        )
        self._window.closing.connect(self._on_window_closing)
        self._window.minimized_to_tray.connect(self._on_minimized_to_tray)

        # Create system tray
        self._setup_tray()

        # Show window (unless start minimized)
        if self.start_minimized or self._settings.ui.start_minimized:
            self._tray.showMessage(
                "Strawberry AI",
                "Running in background. Click tray icon to open.",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )
        else:
            self._window.show()

        # Run event loop
        if HAS_QASYNC:
            # Use qasync for proper async integration
            import asyncio
            loop = qasync.QEventLoop(self._app)
            asyncio.set_event_loop(loop)

            with loop:
                return loop.run_forever()
        else:
            # Fallback to standard Qt event loop
            # Note: async operations may not work properly
            return self._app.exec()

    def _setup_tray(self):
        """Set up system tray icon and menu."""
        # Create tray icon
        self._tray = QSystemTrayIcon(self._app)
        self._tray.setIcon(create_strawberry_icon())
        self._tray.setToolTip("Strawberry AI")

        # Create tray menu
        menu = QMenu()

        # Show/Hide action
        show_action = QAction("Show Window", menu)
        show_action.triggered.connect(self._show_window)
        menu.addAction(show_action)

        menu.addSeparator()

        # New chat action
        new_chat_action = QAction("New Chat", menu)
        new_chat_action.triggered.connect(self._new_chat)
        menu.addAction(new_chat_action)

        settings_action = QAction("Settings...", menu)
        settings_action.triggered.connect(self._open_settings)
        menu.addAction(settings_action)

        menu.addSeparator()

        # Quit action
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self._tray.setContextMenu(menu)

        # Handle tray activation (click)
        self._tray.activated.connect(self._on_tray_activated)

        # Show tray icon
        self._tray.show()

    def _show_window(self):
        """Show and activate the main window."""
        if self._window:
            self._window.show_and_activate()

    def _new_chat(self):
        """Start a new chat."""
        if self._window:
            self._window._on_new_chat()
            self._show_window()

    def _open_settings(self):
        """Open the settings dialog."""
        if self._window:
            self._show_window()
            self._window.open_settings_dialog()

    def _quit(self):
        """Quit the application."""
        if self._window:
            self._window.close()
        if self._tray:
            self._tray.hide()
        if self._app:
            self._app.quit()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason):
        """Handle tray icon activation."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            # Single click - toggle window
            if self._window and self._window.isVisible():
                self._window.hide()
            else:
                self._show_window()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            # Double click - show window
            self._show_window()

    def _on_window_closing(self):
        """Handle window close - minimize to tray instead of quitting."""
        # Window is closing, but app continues in tray
        pass

    def _on_minimized_to_tray(self):
        """Handle minimize to tray."""
        if self._tray:
            self._tray.showMessage(
                "Strawberry AI",
                "Minimized to tray. Click icon to restore.",
                QSystemTrayIcon.MessageIcon.Information,
                1500
            )


def main():
    """Entry point for GUI application."""
    import argparse

    parser = argparse.ArgumentParser(description="Strawberry AI Desktop")
    parser.add_argument(
        "-c", "--config",
        type=Path,
        default=get_project_root() / "src" / "config" / "config.yaml",
        help="Path to configuration file",
    )
    parser.add_argument(
        "--minimized",
        action="store_true",
        help="Start minimized to system tray",
    )

    args = parser.parse_args()

    app = StrawberryApp(
        config_path=args.config,
        start_minimized=args.minimized,
    )

    sys.exit(app.run())


if __name__ == "__main__":
    main()

