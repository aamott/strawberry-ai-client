"""Voice events and event emitter.

This module contains the event definitions and the thread-safe event emitter
used by VoiceCore.
"""

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from .state import VoiceState

logger = logging.getLogger(__name__)


# =============================================================================
# Events
# =============================================================================


@dataclass
class VoiceEvent:
    """Base class for voice events."""

    session_id: str = ""


@dataclass
class VoiceStateChanged(VoiceEvent):
    """Voice state has changed."""

    old_state: VoiceState = VoiceState.STOPPED
    new_state: VoiceState = VoiceState.STOPPED


@dataclass
class VoiceWakeWordDetected(VoiceEvent):
    """Wake word was detected."""

    keyword: str = ""
    keyword_index: int = 0


@dataclass
class VoiceListening(VoiceEvent):
    """Voice is now listening for speech."""

    pass


@dataclass
class VoiceNoSpeechDetected(VoiceEvent):
    """Recording ended without detecting any speech.

    This is emitted when we enter LISTENING (after wake word / PTT) but VAD
    determines that no speech occurred before recording ended.
    """

    duration_s: float = 0.0


@dataclass
class VoiceTranscription(VoiceEvent):
    """Speech was transcribed."""

    text: str = ""
    is_final: bool = True
    confidence: float = 1.0


@dataclass
class VoiceResponse(VoiceEvent):
    """Response text (for TTS or display)."""

    text: str = ""


@dataclass
class VoiceSpeaking(VoiceEvent):
    """TTS is playing response."""

    text: str = ""


@dataclass
class VoiceError(VoiceEvent):
    """An error occurred in voice pipeline."""

    error: str = ""
    exception: Optional[Exception] = None


# =============================================================================
# Event Emitter
# =============================================================================


class VoiceEventEmitter:
    """Thread-safe event emitter for voice events."""

    def __init__(self):
        self._listeners: List[Callable[[VoiceEvent], Any]] = []
        self._listeners_lock = threading.Lock()
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._session_id = ""

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Set the event loop to use for marshaling events."""
        self._event_loop = loop

    def set_session_id(self, session_id: str) -> None:
        """Set current session ID to attach to events."""
        self._session_id = session_id

    def add_listener(self, listener: Callable[[VoiceEvent], Any]) -> None:
        """Add event listener."""
        with self._listeners_lock:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[VoiceEvent], Any]) -> None:
        """Remove event listener."""
        with self._listeners_lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def emit(self, event: VoiceEvent) -> None:
        """Emit event to all listeners.

        Ensures all listeners are invoked on the asyncio event loop thread.
        If called from a worker thread, marshals the event to the loop.
        """
        # Check if we need to marshal to the event loop
        if self._event_loop and not self._event_loop.is_closed():
            try:
                running_loop = asyncio.get_running_loop()
                if running_loop is not self._event_loop:
                    # We are on a loop, but not THE voice loop (unlikely but possible)
                    # or we hit RuntimeError below.
                    self._event_loop.call_soon_threadsafe(self.emit, event)
                    return
            except RuntimeError:
                # We are not on any asyncio loop (e.g. worker thread)
                self._event_loop.call_soon_threadsafe(self.emit, event)
                return

        # We are on the event loop (or no loop is configured), proceed.
        event.session_id = self._session_id
        with self._listeners_lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                result = listener(event)
                if asyncio.iscoroutine(result):
                    # We are already on the loop, so just schedule it
                    if self._event_loop and not self._event_loop.is_closed():
                        self._event_loop.create_task(result)
            except Exception as e:
                logger.error(f"Error in voice event listener: {e}")
