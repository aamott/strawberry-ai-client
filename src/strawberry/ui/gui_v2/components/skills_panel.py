"""Skills browser panel — shows loaded skills, health, and enable/disable toggles.

This component receives plain dicts from MainWindow (no SkillService import).
It emits signals that bubble up through MainWindow to IntegratedApp.
"""

import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..utils.icons import Icons

logger = logging.getLogger(__name__)


class _SkillCard(QFrame):
    """A single skill row with name, method count, and enable/disable toggle."""

    toggled = Signal(str, bool)  # skill_name, enabled

    def __init__(
        self,
        skill: Dict[str, Any],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._name = skill["name"]
        self.setObjectName("SkillCard")
        self._setup_ui(skill)

    def _setup_ui(self, skill: Dict[str, Any]) -> None:
        """Build the card layout."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        # Health-aware icon
        healthy = skill.get("healthy", True)
        icon_text = Icons.SUCCESS if healthy else Icons.WARNING
        icon = QLabel(icon_text)
        icon.setObjectName("SkillCardIcon")
        if not healthy:
            icon.setToolTip(skill.get("health_message", "Unhealthy"))
        layout.addWidget(icon)

        # Info column
        info = QVBoxLayout()
        info.setSpacing(2)

        name_label = QLabel(skill["name"])
        name_label.setObjectName("SkillCardName")
        info.addWidget(name_label)

        method_count = skill.get("method_count", 0)
        source = skill.get("source", "")
        # Show just the last path component for brevity
        if "/" in source:
            source = source.rsplit("/", 1)[-1]
        elif "\\" in source:
            source = source.rsplit("\\", 1)[-1]
        detail = f"{method_count} method{'s' if method_count != 1 else ''}"
        if source:
            detail += f"  ·  {source}"
        detail_label = QLabel(detail)
        detail_label.setObjectName("SkillCardDetail")
        info.addWidget(detail_label)

        # Health warning message (visible inline when unhealthy)
        if not healthy:
            health_msg = skill.get("health_message", "")
            if health_msg:
                health_label = QLabel(f"{Icons.WARNING}  {health_msg}")
                health_label.setObjectName("SkillCardHealthWarning")
                health_label.setWordWrap(True)
                info.addWidget(health_label)

        # Method list (collapsed by default, shown as tooltip)
        methods = skill.get("methods", [])
        if methods:
            method_names = ", ".join(m["name"] for m in methods[:10])
            if len(methods) > 10:
                method_names += f" (+{len(methods) - 10} more)"
            name_label.setToolTip(method_names)

        layout.addLayout(info, 1)

        # Enable/disable toggle
        self._toggle = QCheckBox()
        self._toggle.setObjectName("SkillToggle")
        self._toggle.setChecked(skill.get("enabled", True))
        self._toggle.setToolTip("Enable or disable this skill")
        self._toggle.toggled.connect(
            lambda checked: self.toggled.emit(self._name, checked)
        )
        layout.addWidget(self._toggle)

    def set_enabled(self, enabled: bool) -> None:
        """Update the toggle state without emitting a signal."""
        self._toggle.blockSignals(True)
        self._toggle.setChecked(enabled)
        self._toggle.blockSignals(False)
        # Update visual state
        self.setProperty("disabled_skill", "false" if enabled else "true")
        self.style().unpolish(self)
        self.style().polish(self)


class _FailureCard(QFrame):
    """A card showing a skill that failed to load."""

    def __init__(
        self,
        failure: Dict[str, str],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setObjectName("SkillFailureCard")
        self._setup_ui(failure)

    def _setup_ui(self, failure: Dict[str, str]) -> None:
        """Build the failure card layout."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        icon = QLabel(Icons.ERROR)
        icon.setObjectName("SkillFailureIcon")
        layout.addWidget(icon)

        info = QVBoxLayout()
        info.setSpacing(2)

        name = QLabel(failure.get("source", "Unknown"))
        name.setObjectName("SkillFailureName")
        info.addWidget(name)

        error = QLabel(failure.get("error", "Unknown error"))
        error.setObjectName("SkillFailureError")
        error.setWordWrap(True)
        info.addWidget(error)

        layout.addLayout(info, 1)


class SkillsPanel(QFrame):
    """Skills browser panel.

    Displays loaded skills with enable/disable toggles and failed skills.
    Receives data as plain dicts — no backend imports.

    Signals:
        skill_toggled: Emitted when user toggles a skill (str: name, bool: enabled)
    """

    skill_toggled = Signal(str, bool)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("SkillsPanel")
        self._skill_cards: dict[str, _SkillCard] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the panel layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        header = QLabel(f"{Icons.SKILLS}  Skills")
        header.setObjectName("SkillsPanelHeader")
        layout.addWidget(header)

        # Summary line (updated dynamically)
        self._summary = QLabel("Loading skills...")
        self._summary.setObjectName("SkillsPanelSummary")
        layout.addWidget(self._summary)

        # Scrollable list
        scroll = QScrollArea()
        scroll.setObjectName("SkillsScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(scroll, 1)

        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)
        self._list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self._list_container)

    def set_data(
        self,
        skills: List[Dict[str, Any]],
        failures: List[Dict[str, str]],
    ) -> None:
        """Populate or refresh the panel with skill data.

        Args:
            skills: List of skill summary dicts.
            failures: List of failure dicts.
        """
        # Clear existing cards
        self._skill_cards.clear()
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Failures section
        if failures:
            fail_header = QLabel(f"{Icons.WARNING}  Failed to load")
            fail_header.setObjectName("SkillsSectionHeader")
            self._list_layout.addWidget(fail_header)

            for failure in failures:
                card = _FailureCard(failure)
                self._list_layout.addWidget(card)

        # Loaded skills section
        if skills:
            loaded_header = QLabel(
                f"{Icons.SUCCESS}  Loaded ({len(skills)})"
            )
            loaded_header.setObjectName("SkillsSectionHeader")
            self._list_layout.addWidget(loaded_header)

            for skill in skills:
                card = _SkillCard(skill)
                card.toggled.connect(self.skill_toggled)
                self._list_layout.addWidget(card)
                self._skill_cards[skill["name"]] = card

        # Update summary
        enabled = sum(1 for s in skills if s.get("enabled", True))
        unhealthy = sum(1 for s in skills if not s.get("healthy", True))
        total = len(skills)
        parts = [f"{total} skill{'s' if total != 1 else ''} loaded"]
        if enabled < total:
            parts.append(f"{total - enabled} disabled")
        if unhealthy:
            parts.append(f"{unhealthy} unhealthy")
        if failures:
            parts.append(f"{len(failures)} failed")
        self._summary.setText("  ·  ".join(parts))

    def update_skill_status(self, name: str, enabled: bool) -> None:
        """Update a single skill's toggle state.

        Args:
            name: Skill class name.
            enabled: New enabled state.
        """
        card = self._skill_cards.get(name)
        if card:
            card.set_enabled(enabled)
