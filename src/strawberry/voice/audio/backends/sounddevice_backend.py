"""Audio backend using sounddevice library."""

import queue
from typing import Optional

import numpy as np

from ..base import AudioBackend


class SoundDeviceBackend(AudioBackend):
    """Audio backend using sounddevice library.

    This is the default backend - cross-platform and reliable.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_length_ms: int = 30,
        device: Optional[int] = None,
    ):
        """Initialize sounddevice backend.

        Args:
            sample_rate: Audio sample rate in Hz
            frame_length_ms: Length of each audio frame in milliseconds
            device: Input device index (None for default)
        """
        super().__init__(sample_rate, frame_length_ms)
        self._device = device
        self._stream = None
        self._queue: Optional[queue.Queue] = None

    def start(self) -> None:
        """Start the audio stream."""
        if self._stream is not None:
            return

        import sounddevice as sd

        self._queue = queue.Queue()
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self.frame_length,
            device=self._device,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        """Stop the audio stream."""
        if self._stream is None:
            return

        self._stream.stop()
        self._stream.close()
        self._stream = None
        self._queue = None

    def _callback(self, indata, frames, time_info, status):
        """Sounddevice callback - called from audio thread."""
        if status:
            print(f"Audio status: {status}")
        # Flatten from (frames, channels) to (frames,)
        self._queue.put(indata.copy().flatten())

    def read_frame(self) -> np.ndarray:
        """Read a single audio frame.

        Returns:
            numpy array of audio samples (int16)

        Raises:
            RuntimeError: If stream is not active
        """
        if self._queue is None:
            raise RuntimeError("Audio stream not started")

        try:
            return self._queue.get(timeout=1.0)
        except queue.Empty:
            raise RuntimeError("Audio read timeout")

    @property
    def is_active(self) -> bool:
        """Check if stream is currently active."""
        return self._stream is not None and self._stream.active
