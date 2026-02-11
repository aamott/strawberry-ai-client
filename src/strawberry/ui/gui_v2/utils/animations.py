"""Animation utilities for GUI V2."""

from typing import Callable, Optional

from PySide6.QtCore import Property, QEasingCurve, QObject, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget


def animate_expand(
    widget: QWidget,
    start_width: int,
    end_width: int,
    duration: int = 200,
    on_finished: Optional[Callable] = None,
) -> QPropertyAnimation:
    """Animate widget width expansion.

    Args:
        widget: Widget to animate
        start_width: Starting width in pixels
        end_width: Ending width in pixels
        duration: Animation duration in milliseconds
        on_finished: Optional callback when animation completes

    Returns:
        The animation object (keep a reference to prevent garbage collection)
    """
    animation = QPropertyAnimation(widget, b"minimumWidth")
    animation.setDuration(duration)
    animation.setStartValue(start_width)
    animation.setEndValue(end_width)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    if on_finished:
        animation.finished.connect(on_finished)

    animation.start()
    return animation


def animate_collapse(
    widget: QWidget,
    start_width: int,
    end_width: int,
    duration: int = 200,
    on_finished: Optional[Callable] = None,
) -> QPropertyAnimation:
    """Animate widget width collapse.

    Args:
        widget: Widget to animate
        start_width: Starting width in pixels
        end_width: Ending width in pixels
        duration: Animation duration in milliseconds
        on_finished: Optional callback when animation completes

    Returns:
        The animation object (keep a reference to prevent garbage collection)
    """
    animation = QPropertyAnimation(widget, b"minimumWidth")
    animation.setDuration(duration)
    animation.setStartValue(start_width)
    animation.setEndValue(end_width)
    animation.setEasingCurve(QEasingCurve.Type.InCubic)

    if on_finished:
        animation.finished.connect(on_finished)

    animation.start()
    return animation


def animate_fade_in(
    widget: QWidget,
    duration: int = 150,
    on_finished: Optional[Callable] = None,
) -> QPropertyAnimation:
    """Animate widget fade in.

    Args:
        widget: Widget to animate
        duration: Animation duration in milliseconds
        on_finished: Optional callback when animation completes

    Returns:
        The animation object (keep a reference to prevent garbage collection)
    """
    # Ensure widget has opacity effect
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)

    animation = QPropertyAnimation(effect, b"opacity")
    animation.setDuration(duration)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    if on_finished:
        animation.finished.connect(on_finished)

    widget.show()
    animation.start()
    return animation


def animate_fade_out(
    widget: QWidget,
    duration: int = 150,
    hide_on_finish: bool = True,
    on_finished: Optional[Callable] = None,
) -> QPropertyAnimation:
    """Animate widget fade out.

    Args:
        widget: Widget to animate
        duration: Animation duration in milliseconds
        hide_on_finish: Whether to hide the widget when animation completes
        on_finished: Optional callback when animation completes

    Returns:
        The animation object (keep a reference to prevent garbage collection)
    """
    # Ensure widget has opacity effect
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)

    animation = QPropertyAnimation(effect, b"opacity")
    animation.setDuration(duration)
    animation.setStartValue(1.0)
    animation.setEndValue(0.0)
    animation.setEasingCurve(QEasingCurve.Type.InCubic)

    def on_complete():
        if hide_on_finish:
            widget.hide()
        if on_finished:
            on_finished()

    animation.finished.connect(on_complete)
    animation.start()
    return animation


class AnimatedWidget(QObject):
    """Mixin for widgets that need animated height changes.

    Use this when you need to animate a widget's height, such as
    for expanding/collapsing tool call details.
    """

    def __init__(self, widget: QWidget):
        super().__init__(widget)
        self._widget = widget
        self._target_height = widget.height()
        self._animation: Optional[QPropertyAnimation] = None

    def _get_animated_height(self) -> int:
        return self._widget.maximumHeight()

    def _set_animated_height(self, height: int) -> None:
        self._widget.setMaximumHeight(height)

    animated_height = Property(int, _get_animated_height, _set_animated_height)

    def animate_height(
        self,
        target_height: int,
        duration: int = 200,
        on_finished: Optional[Callable] = None,
    ) -> None:
        """Animate to target height.

        Args:
            target_height: Target height in pixels
            duration: Animation duration in milliseconds
            on_finished: Optional callback when animation completes
        """
        if (
            self._animation
            and self._animation.state() == QPropertyAnimation.State.Running
        ):
            self._animation.stop()

        self._animation = QPropertyAnimation(self, b"animated_height")
        self._animation.setDuration(duration)
        self._animation.setStartValue(self._widget.height())
        self._animation.setEndValue(target_height)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        if on_finished:
            self._animation.finished.connect(on_finished)

        self._animation.start()
