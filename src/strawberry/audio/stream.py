"""Audio stream manager with multiple consumers."""

import threading
from collections import deque
from typing import Callable, List, Optional

import numpy as np

from .base import AudioBackend


class AudioStream:
    """Manages a single continuous audio stream with multiple consumers.
    
    This is the core of the "no blip" architecture - one stream feeds
    multiple consumers (wake word, VAD, STT) without stopping/restarting.
    """

    def __init__(
        self,
        backend: AudioBackend,
        buffer_size: int = 100,
        suppress_errors: bool = False,
    ):
        """Initialize the audio stream manager.
        
        Args:
            backend: Audio backend to use for capture
            buffer_size: Number of frames to keep in rolling buffer
            suppress_errors: If True, don't print subscriber errors (for testing)
        """
        self.backend = backend
        self._buffer: deque[np.ndarray] = deque(maxlen=buffer_size)
        self._subscribers: List[Callable[[np.ndarray], None]] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._suppress_errors = suppress_errors

    @property
    def sample_rate(self) -> int:
        """Audio sample rate from backend."""
        return self.backend.sample_rate

    @property
    def frame_length(self) -> int:
        """Frame length in samples from backend."""
        return self.backend.frame_length

    @property
    def is_active(self) -> bool:
        """Check if stream is currently active."""
        return self._running and self.backend.is_active

    def subscribe(self, callback: Callable[[np.ndarray], None]) -> None:
        """Add a subscriber to receive audio frames.
        
        Args:
            callback: Function to call with each audio frame
        """
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[np.ndarray], None]) -> None:
        """Remove a subscriber.
        
        Args:
            callback: Previously registered callback to remove
        """
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def get_buffer(self, frames: int) -> np.ndarray:
        """Get the last N frames from the buffer.
        
        Useful for including audio from just before wake word detection.
        
        Args:
            frames: Number of frames to retrieve
            
        Returns:
            Concatenated audio samples
        """
        with self._lock:
            buffer_list = list(self._buffer)
            if not buffer_list:
                return np.array([], dtype=np.int16)
            return np.concatenate(buffer_list[-frames:])

    def clear_buffer(self) -> None:
        """Clear the rolling buffer."""
        with self._lock:
            self._buffer.clear()

    def start(self) -> None:
        """Start streaming audio to all subscribers."""
        if self._running:
            return

        self._running = True
        self.backend.start()
        self._thread = threading.Thread(target=self._stream_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the audio stream."""
        self._running = False
        self.backend.stop()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _stream_loop(self) -> None:
        """Main streaming loop - distributes frames to subscribers."""
        while self._running:
            try:
                frame = self.backend.read_frame()
            except Exception:
                if not self._running:
                    break
                raise

            # Add to rolling buffer
            with self._lock:
                self._buffer.append(frame)
                subscribers = list(self._subscribers)

            # Notify all subscribers (outside lock to prevent deadlock)
            for subscriber in subscribers:
                try:
                    subscriber(frame)
                except Exception as e:
                    # Log but don't crash the stream
                    if not self._suppress_errors:
                        print(f"Subscriber error: {e}")

    def __enter__(self):
        """Context manager entry - start stream."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - stop stream."""
        self.stop()
        return False

