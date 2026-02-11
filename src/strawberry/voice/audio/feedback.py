"""Audio feedback module for voice interaction cues.

Generates and plays simple tones for various events:
- Wake word detected (ascending tone)
- Recording started (short beep)
- Recording complete (descending tone)
- Processing (soft pulse)
- Error (low descending tone)
- Ready (pleasant startup chime)
"""

import logging
import threading
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class FeedbackSound(Enum):
    """Available feedback sounds."""

    WAKE_DETECTED = auto()  # Wake word heard - start listening
    RECORDING_START = auto()  # Recording has started
    RECORDING_END = auto()  # Recording complete, processing
    PROCESSING = auto()  # Waiting for response (subtle)
    SUCCESS = auto()  # Operation successful
    ERROR = auto()  # Something went wrong
    READY = auto()  # System ready / startup


@dataclass
class ToneConfig:
    """Configuration for a generated tone."""

    frequencies: list[float]  # Hz - can be multiple for chord
    duration: float  # seconds
    volume: float = 0.3  # 0.0 to 1.0
    fade_in: float = 0.01  # seconds
    fade_out: float = 0.05  # seconds
    wave_type: str = "sine"  # sine, square, triangle


# Sound definitions - pleasant, non-intrusive tones
SOUND_CONFIGS: dict[FeedbackSound, ToneConfig] = {
    FeedbackSound.WAKE_DETECTED: ToneConfig(
        frequencies=[440, 554, 659],  # A4, C#5, E5 (A major chord, ascending)
        duration=0.15,
        volume=0.25,
        fade_out=0.08,
    ),
    FeedbackSound.RECORDING_START: ToneConfig(
        frequencies=[880],  # A5 - single high beep
        duration=0.08,
        volume=0.2,
        fade_out=0.03,
    ),
    FeedbackSound.RECORDING_END: ToneConfig(
        frequencies=[659, 554],  # E5, C#5 - descending
        duration=0.12,
        volume=0.2,
        fade_out=0.05,
    ),
    FeedbackSound.PROCESSING: ToneConfig(
        frequencies=[330],  # E4 - soft low tone
        duration=0.1,
        volume=0.1,
        fade_out=0.05,
    ),
    FeedbackSound.SUCCESS: ToneConfig(
        frequencies=[523, 659, 784],  # C5, E5, G5 (C major)
        duration=0.2,
        volume=0.2,
        fade_out=0.1,
    ),
    FeedbackSound.ERROR: ToneConfig(
        frequencies=[220, 185],  # A3, F#3 - dissonant, descending
        duration=0.25,
        volume=0.25,
        fade_out=0.1,
    ),
    FeedbackSound.READY: ToneConfig(
        frequencies=[523, 659, 784, 1047],  # C5, E5, G5, C6 - ascending arpeggio
        duration=0.4,
        volume=0.2,
        fade_out=0.15,
    ),
}


class AudioFeedback:
    """Plays audio feedback sounds.

    Uses sounddevice to play generated tones without blocking.
    Thread-safe for use from any thread.

    Usage:
        feedback = AudioFeedback()
        feedback.play(FeedbackSound.WAKE_DETECTED)
    """

    def __init__(
        self,
        sample_rate: int = 44100,
        enabled: bool = True,
    ):
        """Initialize audio feedback.

        Args:
            sample_rate: Output sample rate
            enabled: Whether feedback is enabled
        """
        self.sample_rate = sample_rate
        self.enabled = enabled
        self._lock = threading.Lock()
        self._playing = False

        # Pre-generate all sounds for instant playback
        self._sounds: dict[FeedbackSound, np.ndarray] = {}
        self._generate_all_sounds()

    def _generate_all_sounds(self):
        """Pre-generate all feedback sounds."""
        for sound_type, config in SOUND_CONFIGS.items():
            self._sounds[sound_type] = self._generate_tone(config)

    @staticmethod
    def _generate_waveform(
        freq: float,
        t: np.ndarray,
        wave_type: str,
    ) -> np.ndarray:
        """Generate a single-frequency waveform."""
        if wave_type == "square":
            return np.sign(np.sin(2 * np.pi * freq * t))
        if wave_type == "triangle":
            return 2 * np.abs(2 * (t * freq - np.floor(t * freq + 0.5))) - 1
        # Default: sine
        return np.sin(2 * np.pi * freq * t)

    def _generate_tone(self, config: ToneConfig) -> np.ndarray:
        """Generate a tone or chord based on configuration.

        Args:
            config: Tone configuration

        Returns:
            Audio samples as float32 array
        """
        num_samples = int(self.sample_rate * config.duration)
        t = np.linspace(0, config.duration, num_samples, dtype=np.float32)
        audio = np.zeros(num_samples, dtype=np.float32)
        is_arpeggio = len(config.frequencies) > 2

        for i, freq in enumerate(config.frequencies):
            if is_arpeggio:
                delay_samples = int(i * 0.03 * self.sample_rate)
                wave_len = num_samples - delay_samples
                wave = np.zeros(num_samples, dtype=np.float32)
                if wave_len > 0:
                    wave[delay_samples:] = self._generate_waveform(
                        freq,
                        t[:wave_len],
                        config.wave_type,
                    )
            else:
                wave = self._generate_waveform(freq, t, config.wave_type)
            audio += wave

        # Normalize, apply volume and fade envelope
        audio /= len(config.frequencies)
        audio *= config.volume

        fade_in_samples = int(config.fade_in * self.sample_rate)
        fade_out_samples = int(config.fade_out * self.sample_rate)
        if fade_in_samples > 0:
            audio[:fade_in_samples] *= np.linspace(0, 1, fade_in_samples)
        if fade_out_samples > 0:
            audio[-fade_out_samples:] *= np.linspace(1, 0, fade_out_samples)

        return audio

    def play(self, sound: FeedbackSound, blocking: bool = False):
        """Play a feedback sound.

        Args:
            sound: The sound to play
            blocking: If True, wait for sound to complete
        """
        if not self.enabled:
            return

        if sound not in self._sounds:
            logger.warning(f"Unknown sound: {sound}")
            return

        audio = self._sounds[sound]

        if blocking:
            self._play_audio(audio)
        else:
            # Play in background thread
            thread = threading.Thread(
                target=self._play_audio,
                args=(audio,),
                daemon=True,
            )
            thread.start()

    def _play_audio(self, audio: np.ndarray):
        """Play audio samples (internal)."""
        with self._lock:
            if self._playing:
                return  # Don't overlap sounds
            self._playing = True

        try:
            import sounddevice as sd

            sd.play(audio, self.sample_rate)
            sd.wait()
        except Exception as e:
            logger.warning(f"Failed to play audio feedback: {e}")
        finally:
            with self._lock:
                self._playing = False

    def set_enabled(self, enabled: bool):
        """Enable or disable audio feedback."""
        self.enabled = enabled

    def play_wake_detected(self):
        """Convenience: Play wake word detected sound."""
        self.play(FeedbackSound.WAKE_DETECTED)

    def play_recording_start(self):
        """Convenience: Play recording started sound."""
        self.play(FeedbackSound.RECORDING_START)

    def play_recording_end(self):
        """Convenience: Play recording complete sound."""
        self.play(FeedbackSound.RECORDING_END)

    def play_processing(self):
        """Convenience: Play processing sound."""
        self.play(FeedbackSound.PROCESSING)

    def play_success(self):
        """Convenience: Play success sound."""
        self.play(FeedbackSound.SUCCESS)

    def play_error(self):
        """Convenience: Play error sound."""
        self.play(FeedbackSound.ERROR)

    def play_ready(self):
        """Convenience: Play ready/startup sound."""
        self.play(FeedbackSound.READY)


# Global instance for easy access
_feedback_instance: Optional[AudioFeedback] = None


def get_feedback(enabled: bool = True) -> AudioFeedback:
    """Get or create the global audio feedback instance.

    Args:
        enabled: Whether feedback should be enabled

    Returns:
        AudioFeedback instance
    """
    global _feedback_instance
    if _feedback_instance is None:
        _feedback_instance = AudioFeedback(enabled=enabled)
    else:
        _feedback_instance.set_enabled(enabled)
    return _feedback_instance
