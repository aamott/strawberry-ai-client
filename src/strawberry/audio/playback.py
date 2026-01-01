"""Audio playback for TTS output."""

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class AudioPlayer:
    """Simple audio playback using sounddevice.
    
    Handles playing TTS audio chunks through the system's default output device.
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

    def _ensure_sounddevice(self):
        if self._sd_import_attempted:
            return
        self._sd_import_attempted = True
        try:
            import sounddevice as sd
            self._sd = sd
        except ImportError:
            logger.warning("sounddevice not available for audio playback")

    def play(self, audio: np.ndarray, sample_rate: Optional[int] = None, blocking: bool = True):
        """Play audio samples.
        
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

        logger.debug(f"Playing audio: {len(audio)} samples @ {sr}Hz, device={self._device}")

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

    def stop(self):
        """Stop current playback."""
        if self._sd and self._play_called:
            try:
                self._sd.stop()
            except Exception:
                pass
            finally:
                self._play_called = False

    def wait(self):
        """Wait for current playback to finish."""
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

