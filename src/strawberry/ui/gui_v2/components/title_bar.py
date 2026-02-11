"""Custom frameless window title bar for GUI V2."""

from typing import Optional

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QWidget,
)

from ..utils.icons import Icons


class TitleBar(QFrame):
    """Custom frameless window title bar.

    Provides window controls (minimize, maximize, close) and supports
    window dragging. Emits signals for menu and window control actions.

    Signals:
        menu_clicked: Emitted when hamburger menu button is clicked
        minimize_clicked: Emitted when minimize button is clicked
        maximize_clicked: Emitted when maximize button is clicked
        close_clicked: Emitted when close button is clicked
    """

    menu_clicked = Signal()
    minimize_clicked = Signal()
    maximize_clicked = Signal()
    close_clicked = Signal()

    # Height of the title bar
    HEIGHT = 40

    def __init__(self, title: str = "Strawberry AI", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._title = title
        self._drag_position: Optional[QPoint] = None
        self._is_maximized = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Initialize the UI layout."""
        self.setObjectName("TitleBar")
        self.setFixedHeight(self.HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(4)

        # Menu button (hamburger)
        self._menu_btn = QToolButton()
        self._menu_btn.setText(Icons.MENU)
        self._menu_btn.setToolTip("Menu")
        self._menu_btn.clicked.connect(self.menu_clicked.emit)
        layout.addWidget(self._menu_btn)

        # Spacer
        layout.addSpacing(8)

        # App title
        self._title_label = QLabel(self._title)
        self._title_label.setObjectName("AppTitle")
        layout.addWidget(self._title_label)

        # Stretch to push window controls to the right
        layout.addStretch()

        # Window controls
        self._minimize_btn = QToolButton()
        self._minimize_btn.setText(Icons.MINIMIZE)
        self._minimize_btn.setToolTip("Minimize")
        self._minimize_btn.clicked.connect(self.minimize_clicked.emit)
        layout.addWidget(self._minimize_btn)

        self._maximize_btn = QToolButton()
        self._maximize_btn.setText(Icons.MAXIMIZE)
        self._maximize_btn.setToolTip("Maximize")
        self._maximize_btn.clicked.connect(self._on_maximize_clicked)
        layout.addWidget(self._maximize_btn)

        self._close_btn = QToolButton()
        self._close_btn.setObjectName("CloseButton")
        self._close_btn.setText(Icons.CLOSE)
        self._close_btn.setToolTip("Close")
        self._close_btn.clicked.connect(self.close_clicked.emit)
        layout.addWidget(self._close_btn)

    def _on_maximize_clicked(self) -> None:
        """Handle maximize button click."""
        self._is_maximized = not self._is_maximized
        self._maximize_btn.setText(
            Icons.RESTORE if self._is_maximized else Icons.MAXIMIZE
        )
        self._maximize_btn.setToolTip("Restore" if self._is_maximized else "Maximize")
        self.maximize_clicked.emit()

    def set_maximized(self, maximized: bool) -> None:
        """Update the maximize button state.

        Call this when the window state changes externally.
        """
        self._is_maximized = maximized
        self._maximize_btn.setText(Icons.RESTORE if maximized else Icons.MAXIMIZE)
        self._maximize_btn.setToolTip("Restore" if maximized else "Maximize")

    def set_title(self, title: str) -> None:
        """Update the title text."""
        self._title = title
        self._title_label.setText(title)

    # Window dragging support
    def mousePressEvent(self, event) -> None:
        """Start window drag on left mouse button press."""
        if event.button() == Qt.MouseButton.LeftButton:
            # Get the main window
            window = self.window()
            if window:
                global_pos = event.globalPosition().toPoint()
                self._drag_position = global_pos - window.frameGeometry().topLeft()
                event.accept()

    def mouseMoveEvent(self, event) -> None:
        """Move window during drag."""
        if (
            self._drag_position is not None
            and event.buttons() == Qt.MouseButton.LeftButton
        ):
            window = self.window()
            if window and not self._is_maximized:
                window.move(event.globalPosition().toPoint() - self._drag_position)
                event.accept()

    def mouseReleaseEvent(self, event) -> None:
        """End window drag."""
        self._drag_position = None

    def mouseDoubleClickEvent(self, event) -> None:
        """Toggle maximize on double-click."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_maximize_clicked()
