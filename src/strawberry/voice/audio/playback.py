"""Audio playback for TTS output.

Supports two playback modes:
- **One-shot** (`play`): Plays a single audio buffer via ``sd.play()``.
  Simple but opens/closes a stream per call — fine for complete utterances.
- **Streaming** (`play_stream`): Writes chunks into a persistent
  ``sd.OutputStream`` so back-to-back ~80 ms TTS chunks play without
  gaps or clicks.  Use this in the TTS streaming loop.
"""

import logging
import threading
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class AudioPlayer:
    """Audio playback using sounddevice.

    Handles playing TTS audio through the system's default output device.
    Supports both one-shot and streaming playback modes.
    """

    def __init__(self, sample_rate: int = 22050, device: Optional[int] = None):
        """Initialize audio player.

        Args:
            sample_rate: Sample rate of audio to play
            device: Output device index (None for default)
        """
        self._sample_rate = sample_rate
        self._device = device
        self._sd = None
        self._play_called = False
        self._sd_import_attempted = False

        # Streaming state
        self._stream = None  # sd.OutputStream for streaming mode
        self._stream_lock = threading.Lock()
        self._stopped = threading.Event()

    def _ensure_sounddevice(self):
        """Lazily import sounddevice on first use."""
        if self._sd_import_attempted:
            return
        self._sd_import_attempted = True
        try:
            import sounddevice as sd

            self._sd = sd
        except ImportError:
            logger.warning("sounddevice not available for audio playback")

    # ------------------------------------------------------------------
    # One-shot playback (existing API, unchanged behaviour)
    # ------------------------------------------------------------------

    def play(
        self, audio: np.ndarray, sample_rate: Optional[int] = None, blocking: bool = True
    ):
        """Play audio samples (one-shot).

        Opens a new stream per call. Fine for complete utterances but will
        cause gaps if called rapidly with small chunks — use ``play_stream``
        for that case.

        Args:
            audio: Audio samples (int16 or float32)
            sample_rate: Sample rate (uses default if None)
            blocking: If True, wait for playback to complete
        """
        self._ensure_sounddevice()

        if self._sd is None:
            logger.warning("Cannot play audio: sounddevice not available")
            return

        if len(audio) == 0:
            logger.debug("Empty audio buffer, skipping playback")
            return

        sr = sample_rate or self._sample_rate

        # Convert int16 to float32 for playback
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0

        logger.debug(
            f"Playing audio: {len(audio)} samples @ {sr}Hz, device={self._device}"
        )

        try:
            self._sd.play(audio, sr, device=self._device, blocking=blocking)
            self._play_called = True
        except Exception as e:
            logger.error(f"Audio playback failed: {e}")
            # Try with default device if specific device failed
            if self._device is not None:
                try:
                    logger.info("Retrying with default output device...")
                    self._sd.play(audio, sr, device=None, blocking=blocking)
                    self._play_called = True
                except Exception as e2:
                    logger.error(f"Default device playback also failed: {e2}")

    # ------------------------------------------------------------------
    # Streaming playback (gap-free for small TTS chunks)
    # ------------------------------------------------------------------

    def start_stream(self, sample_rate: Optional[int] = None) -> None:
        """Open a persistent OutputStream for streaming playback.

        Call this once before feeding chunks via ``write_chunk()``, then
        call ``finish_stream()`` when the utterance is complete.

        Args:
            sample_rate: Sample rate for the stream (uses default if None).
        """
        self._ensure_sounddevice()
        if self._sd is None:
            return

        sr = sample_rate or self._sample_rate
        self._stopped.clear()

        with self._stream_lock:
            # Close any leftover stream
            if self._stream is not None:
                try:
                    self._stream.close()
                except Exception:
                    pass

            self._stream = self._sd.OutputStream(
                samplerate=sr,
                channels=1,
                dtype="float32",
                device=self._device,
            )
            self._stream.start()
            logger.debug(f"Opened streaming output @ {sr}Hz")

    def write_chunk(self, audio: np.ndarray) -> None:
        """Write an audio chunk into the open stream.

        Blocks until the chunk has been accepted by the audio backend,
        which provides natural back-pressure so the TTS generator doesn't
        race ahead of playback.

        Args:
            audio: Audio samples (int16 or float32). Will be converted
                   to float32 mono if needed.
        """
        if self._stopped.is_set():
            return

        with self._stream_lock:
            if self._stream is None:
                logger.warning("write_chunk called without an open stream")
                return

        if len(audio) == 0:
            return

        # Convert int16 → float32
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0

        # Ensure column vector for single-channel OutputStream
        if audio.ndim == 1:
            audio = audio.reshape(-1, 1)

        try:
            with self._stream_lock:
                if self._stream is not None and not self._stopped.is_set():
                    self._stream.write(audio)
        except Exception as e:
            logger.error(f"Stream write failed: {e}")

    def finish_stream(self) -> None:
        """Close the streaming output after the last chunk.

        Blocks briefly to let the audio backend drain its buffer so the
        tail of the utterance isn't clipped.
        """
        with self._stream_lock:
            stream = self._stream
            self._stream = None

        if stream is not None:
            try:
                stream.stop()
                stream.close()
                logger.debug("Streaming output closed")
            except Exception as e:
                logger.debug(f"Stream close error (usually harmless): {e}")

    # ------------------------------------------------------------------
    # Stop / wait (works for both modes)
    # ------------------------------------------------------------------

    def stop(self):
        """Stop current playback (one-shot or streaming)."""
        self._stopped.set()

        # Stop one-shot playback
        if self._sd and self._play_called:
            try:
                self._sd.stop()
            except Exception:
                pass
            finally:
                self._play_called = False

        # Stop streaming playback
        self.finish_stream()

    def wait(self):
        """Wait for current one-shot playback to finish."""
        if self._sd and self._play_called:
            try:
                self._sd.wait()
            except Exception:
                pass

    @classmethod
    def list_devices(cls) -> list:
        """List available output devices."""
        try:
            import sounddevice as sd

            return sd.query_devices()
        except ImportError:
            return []

    @classmethod
    def get_default_output_device(cls) -> Optional[int]:
        """Get the default output device index."""
        try:
            import sounddevice as sd

            return sd.default.device[1]  # [1] is output device
        except (ImportError, Exception):
            return None
