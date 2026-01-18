"""Offline mode banner widget."""

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from ..theme import Theme


class OfflineModeBanner(QFrame):
    """Banner shown when in offline mode.

    Displays offline status, current model name, and pending sync count.
    Provides a button to manually trigger sync.
    """

    sync_requested = Signal()

    def __init__(self, theme: Optional[Theme] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._theme = theme
        self._model_name: Optional[str] = None
        self._pending_count = 0

        self.setObjectName("offlineBanner")
        self.setVisible(False)  # Hidden by default
        self._setup_ui()
        self._apply_style()

    def _setup_ui(self) -> None:
        """Set up the banner UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        # Warning icon
        self._icon = QLabel("⚠️")
        self._icon.setObjectName("bannerIcon")
        layout.addWidget(self._icon)

        # Status text
        self._text = QLabel("Offline mode")
        self._text.setObjectName("bannerText")
        layout.addWidget(self._text, 1)

        # Pending count label
        self._pending_label = QLabel()
        self._pending_label.setObjectName("pendingLabel")
        self._pending_label.setVisible(False)
        layout.addWidget(self._pending_label)

        # Sync button
        self._sync_btn = QPushButton("Sync Now")
        self._sync_btn.setObjectName("syncButton")
        self._sync_btn.clicked.connect(self.sync_requested.emit)
        layout.addWidget(self._sync_btn)

    def _apply_style(self) -> None:
        """Apply theme-based styling."""
        if not self._theme:
            # Default styling
            self.setStyleSheet(
                """
                #offlineBanner {
                    background-color: #3d3522;
                    border-bottom: 1px solid #665c40;
                }
                #bannerIcon {
                    font-size: 14px;
                }
                #bannerText {
                    color: #ffd866;
                    font-size: 13px;
                }
                #pendingLabel {
                    color: #b0a080;
                    font-size: 12px;
                }
                #syncButton {
                    background-color: #5c5030;
                    color: #ffd866;
                    border: 1px solid #665c40;
                    border-radius: 4px;
                    padding: 4px 12px;
                    font-size: 12px;
                }
                #syncButton:hover {
                    background-color: #6d6040;
                }
                #syncButton:pressed {
                    background-color: #4d4020;
                }
            """
            )
        else:
            # Theme-based styling
            self.setStyleSheet(
                f"""
                #offlineBanner {{
                    background-color: {self._theme.warning}20;
                    border-bottom: 1px solid {self._theme.warning}40;
                }}
                #bannerIcon {{
                    font-size: 14px;
                }}
                #bannerText {{
                    color: {self._theme.warning};
                    font-size: 13px;
                }}
                #pendingLabel {{
                    color: {self._theme.text_muted};
                    font-size: 12px;
                }}
                #syncButton {{
                    background-color: {self._theme.warning}30;
                    color: {self._theme.warning};
                    border: 1px solid {self._theme.warning}50;
                    border-radius: 4px;
                    padding: 4px 12px;
                    font-size: 12px;
                }}
                #syncButton:hover {{
                    background-color: {self._theme.warning}40;
                }}
                #syncButton:pressed {{
                    background-color: {self._theme.warning}20;
                }}
            """
            )

    def set_offline(self, model_name: Optional[str] = None, pending_count: int = 0) -> None:
        """Show offline banner with status.

        Args:
            model_name: Name of the local model being used
            pending_count: Number of items pending sync
        """
        self._model_name = model_name
        self._pending_count = pending_count

        # Update text
        if model_name:
            self._text.setText(f"Using local model ({model_name})")
        else:
            self._text.setText("Using local model")

        # Update pending count
        if pending_count > 0:
            self._pending_label.setText(f"· {pending_count} pending sync")
            self._pending_label.setVisible(True)
        else:
            self._pending_label.setVisible(False)

        self.setVisible(True)

    def set_online(self) -> None:
        """Hide banner when online."""
        self.setVisible(False)

    def set_syncing(self, is_syncing: bool) -> None:
        """Update banner during sync.

        Args:
            is_syncing: True if sync is in progress
        """
        if is_syncing:
            self._sync_btn.setText("Syncing...")
            self._sync_btn.setEnabled(False)
        else:
            self._sync_btn.setText("Sync Now")
            self._sync_btn.setEnabled(True)

    def update_pending_count(self, count: int) -> None:
        """Update pending sync count.

        Args:
            count: Number of items pending sync
        """
        self._pending_count = count
        if count > 0:
            self._pending_label.setText(f"· {count} pending sync")
            self._pending_label.setVisible(True)
        else:
            self._pending_label.setVisible(False)

    def set_theme(self, theme: Theme) -> None:
        """Update theme.

        Args:
            theme: New theme to apply
        """
        self._theme = theme
        self._apply_style()
