"""Sidebar rail component - collapsible navigation."""

from typing import List, Optional

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..utils.icons import Icons


class SessionItem(QFrame):
    """Individual session item in the sidebar."""

    clicked = Signal(str)  # session_id

    def __init__(
        self,
        session_id: str,
        title: str,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._session_id = session_id
        self._title = title
        self._selected = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Initialize the UI."""
        self.setObjectName("SessionItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Session icon
        self._icon_label = QLabel(Icons.CHATS)
        self._icon_label.setToolTip("Chat session")
        layout.addWidget(self._icon_label)

        # Session title
        self._title_label = QLabel(self._title)
        self._title_label.setObjectName("SessionTitle")
        self._title_label.setWordWrap(False)
        layout.addWidget(self._title_label, 1)

    def mousePressEvent(self, event) -> None:
        """Handle mouse press."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._session_id)
            event.accept()
        else:
            super().mousePressEvent(event)

    def set_selected(self, selected: bool) -> None:
        """Set the selected state."""
        self._selected = selected
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_title(self, title: str) -> None:
        """Update the session title."""
        self._title = title
        self._title_label.setText(title)

    @property
    def session_id(self) -> str:
        """Get the session ID."""
        return self._session_id

    @property
    def is_selected(self) -> bool:
        """Check if selected."""
        return self._selected


class NavButton(QWidget):
    """Navigation button with icon and label for the sidebar."""

    clicked = Signal(str)  # nav_id

    def __init__(
        self,
        icon: str,
        label: str,
        nav_id: str,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.nav_id = nav_id
        self.setObjectName(f"NavButton_{nav_id}")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        # Icon button
        self.icon_btn = QToolButton()
        self.icon_btn.setObjectName(f"NavIcon_{nav_id}")
        self.icon_btn.setText(icon)
        self.icon_btn.setToolTip(label)
        self.icon_btn.setCheckable(True)
        self.icon_btn.setAutoExclusive(False)
        self.icon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.icon_btn.clicked.connect(lambda: self.clicked.emit(nav_id))
        layout.addWidget(self.icon_btn)

        # Text label (hidden when collapsed)
        self.label_widget = QLabel(label)
        self.label_widget.setObjectName(f"NavLabel_{nav_id}")
        self.label_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        self.label_widget.setToolTip(label)
        self.label_widget.hide()
        layout.addWidget(self.label_widget, 1)

    def mousePressEvent(self, event) -> None:
        """Forward clicks on the entire container."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.nav_id)
            event.accept()
        else:
            super().mousePressEvent(event)


class SidebarRail(QFrame):
    """Collapsible navigation sidebar.

    Shows an icon rail when collapsed, expands to show full navigation
    with session list when expanded.

    Signals:
        navigation_changed: Emitted when nav item is selected (str: nav_id)
        session_selected: Emitted when a session is clicked (str: session_id)
        new_chat_requested: Emitted when new chat button is clicked
        expand_toggled: Emitted when expand state changes (bool: expanded)
    """

    navigation_changed = Signal(str)
    session_selected = Signal(str)
    new_chat_requested = Signal()
    expand_toggled = Signal(bool)

    # Widths
    COLLAPSED_WIDTH = 48
    EXPANDED_WIDTH = 240

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._expanded = False
        self._current_nav = "chats"
        self._session_items: dict[str, SessionItem] = {}
        self._current_session_id: Optional[str] = None
        self._animation: Optional[QPropertyAnimation] = None
        self._max_animation: Optional[QPropertyAnimation] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Initialize the UI layout."""
        self.setObjectName("SidebarRail")
        self.setFixedWidth(self.COLLAPSED_WIDTH)
        self.setMinimumWidth(self.COLLAPSED_WIDTH)
        self.setMaximumWidth(self.COLLAPSED_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(4)

        # Navigation buttons (always visible)
        self._nav_container = QWidget()
        nav_layout = QVBoxLayout(self._nav_container)
        nav_layout.setContentsMargins(4, 0, 4, 0)
        nav_layout.setSpacing(4)

        # Chats button
        self._chats_btn = self._create_nav_button(Icons.CHATS, "Chats", "chats")
        self._chats_btn.icon_btn.setChecked(True)
        nav_layout.addWidget(self._chats_btn)

        # New chat button
        self._new_chat_btn = self._create_nav_button(Icons.NEW_CHAT, "New Chat", "new_chat")
        # Override click handler for new chat
        self._new_chat_btn.icon_btn.clicked.disconnect()
        self._new_chat_btn.icon_btn.clicked.connect(self.new_chat_requested.emit)
        nav_layout.addWidget(self._new_chat_btn)

        layout.addWidget(self._nav_container)

        # Session list (only visible when expanded)
        self._session_scroll = QScrollArea()
        self._session_scroll.setObjectName("SessionList")
        self._session_scroll.setWidgetResizable(True)
        self._session_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._session_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._session_scroll.hide()

        self._session_container = QWidget()
        self._session_layout = QVBoxLayout(self._session_container)
        self._session_layout.setContentsMargins(4, 8, 4, 8)
        self._session_layout.setSpacing(2)
        self._session_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._session_scroll.setWidget(self._session_container)
        layout.addWidget(self._session_scroll, 1)

        # Stretch
        layout.addStretch()

        # Bottom navigation
        self._bottom_nav = QWidget()
        bottom_layout = QVBoxLayout(self._bottom_nav)
        bottom_layout.setContentsMargins(4, 0, 4, 0)
        bottom_layout.setSpacing(4)

        # Skills button
        self._skills_btn = self._create_nav_button(Icons.SKILLS, "Skills", "skills")
        bottom_layout.addWidget(self._skills_btn)

        # Settings button
        self._settings_btn = self._create_nav_button(Icons.SETTINGS, "Settings", "settings")
        bottom_layout.addWidget(self._settings_btn)

        layout.addWidget(self._bottom_nav)

    def _create_nav_button(self, icon: str, label: str, nav_id: str) -> NavButton:
        """Create a navigation button with icon and optional label.

        Args:
            icon: Icon text
            label: Button label text
            nav_id: Navigation identifier

        Returns:
            NavButton widget with icon button and label
        """
        nav_btn = NavButton(icon, label, nav_id, parent=self)
        nav_btn.clicked.connect(self._on_nav_clicked)
        return nav_btn

    def _on_nav_clicked(self, nav_id: str) -> None:
        """Handle navigation button click."""
        # Uncheck all nav buttons
        for nav_btn in [self._chats_btn, self._skills_btn, self._settings_btn]:
            nav_btn.icon_btn.setChecked(False)

        # Check the clicked button
        btn_map = {
            "chats": self._chats_btn,
            "skills": self._skills_btn,
            "settings": self._settings_btn,
        }
        if nav_id in btn_map:
            btn_map[nav_id].icon_btn.setChecked(True)

        self._current_nav = nav_id

        # Expand sidebar when clicking chats
        if nav_id == "chats" and not self._expanded:
            self.expand()

        self.navigation_changed.emit(nav_id)

    def _on_session_clicked(self, session_id: str) -> None:
        """Handle session item click."""
        # Update selection
        for item in self._session_items.values():
            item.set_selected(item.session_id == session_id)

        self._current_session_id = session_id
        self.session_selected.emit(session_id)

    def expand(self) -> None:
        """Expand the sidebar with animation."""
        if self._expanded:
            return

        self._expanded = True
        self._session_scroll.show()

        # Show nav labels
        for nav_btn in [
            self._chats_btn, self._new_chat_btn, self._skills_btn, self._settings_btn
        ]:
            nav_btn.label_widget.show()

        # Stop any in-flight animations before starting new ones
        self._stop_animations()

        # Animate width
        self._animation = QPropertyAnimation(self, b"minimumWidth")
        self._animation.setDuration(200)
        self._animation.setStartValue(self.COLLAPSED_WIDTH)
        self._animation.setEndValue(self.EXPANDED_WIDTH)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Also animate maximum width
        self._max_animation = QPropertyAnimation(self, b"maximumWidth")
        self._max_animation.setDuration(200)
        self._max_animation.setStartValue(self.COLLAPSED_WIDTH)
        self._max_animation.setEndValue(self.EXPANDED_WIDTH)
        self._max_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._animation.start()
        self._max_animation.start()

        self.expand_toggled.emit(True)

    def collapse(self) -> None:
        """Collapse the sidebar with animation."""
        if not self._expanded:
            return

        self._expanded = False

        # Hide nav labels
        for nav_btn in [
            self._chats_btn, self._new_chat_btn, self._skills_btn, self._settings_btn
        ]:
            nav_btn.label_widget.hide()

        # Stop any in-flight animations before starting new ones
        self._stop_animations()

        # Animate width
        self._animation = QPropertyAnimation(self, b"minimumWidth")
        self._animation.setDuration(200)
        self._animation.setStartValue(self.EXPANDED_WIDTH)
        self._animation.setEndValue(self.COLLAPSED_WIDTH)
        self._animation.setEasingCurve(QEasingCurve.Type.InCubic)
        self._animation.finished.connect(lambda: self._session_scroll.hide())

        # Also animate maximum width
        self._max_animation = QPropertyAnimation(self, b"maximumWidth")
        self._max_animation.setDuration(200)
        self._max_animation.setStartValue(self.EXPANDED_WIDTH)
        self._max_animation.setEndValue(self.COLLAPSED_WIDTH)
        self._max_animation.setEasingCurve(QEasingCurve.Type.InCubic)

        self._animation.start()
        self._max_animation.start()

        self.expand_toggled.emit(False)

    def _stop_animations(self) -> None:
        """Stop any in-flight expand/collapse animations."""
        if self._animation and self._animation.state() == QPropertyAnimation.State.Running:
            self._animation.stop()
        if self._max_animation and self._max_animation.state() == QPropertyAnimation.State.Running:
            self._max_animation.stop()

    def toggle(self) -> None:
        """Toggle the expanded state."""
        if self._expanded:
            self.collapse()
        else:
            self.expand()

    def set_sessions(self, sessions: List[dict]) -> None:
        """Update the session list.

        Args:
            sessions: List of session dicts with 'id' and 'title' keys
        """
        # Clear existing items
        for item in self._session_items.values():
            self._session_layout.removeWidget(item)
            item.deleteLater()
        self._session_items.clear()

        # Add new items
        for session in sessions:
            session_id = session.get("id", "")
            title = session.get("title", "Untitled")

            item = SessionItem(session_id, title)
            item.clicked.connect(self._on_session_clicked)

            if session_id == self._current_session_id:
                item.set_selected(True)

            self._session_layout.addWidget(item)
            self._session_items[session_id] = item

    def add_session(self, session_id: str, title: str) -> None:
        """Add a single session to the list.

        Args:
            session_id: Session ID
            title: Session title
        """
        if session_id in self._session_items:
            return

        item = SessionItem(session_id, title)
        item.clicked.connect(self._on_session_clicked)

        # Insert at top
        self._session_layout.insertWidget(0, item)
        self._session_items[session_id] = item

    def highlight_session(self, session_id: str) -> None:
        """Highlight a session as selected.

        Args:
            session_id: Session ID to highlight
        """
        for item in self._session_items.values():
            item.set_selected(item.session_id == session_id)
        self._current_session_id = session_id

    def update_session_title(self, session_id: str, title: str) -> None:
        """Update a session's title.

        Args:
            session_id: Session ID
            title: New title
        """
        item = self._session_items.get(session_id)
        if item:
            item.set_title(title)

    @property
    def is_expanded(self) -> bool:
        """Check if the sidebar is expanded."""
        return self._expanded

    @property
    def current_nav(self) -> str:
        """Get the current navigation item."""
        return self._current_nav

    @property
    def current_session_id(self) -> Optional[str]:
        """Get the currently selected session ID."""
        return self._current_session_id
