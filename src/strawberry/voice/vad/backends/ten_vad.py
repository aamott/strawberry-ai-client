"""TEN VAD backend.

Requires: pip install git+https://github.com/TEN-framework/ten-vad.git
Also requires: libc++ (Linux: sudo apt install libc++1)

TEN VAD is a lightweight, high-performance voice activity detector that
claims better accuracy than both Silero VAD and WebRTC VAD.

Website: https://github.com/TEN-framework/ten-vad
"""

from typing import ClassVar, List

import numpy as np

from ..base import VADBackend


class TenVAD(VADBackend):
    """VAD using TEN Framework's VAD engine.

    TEN VAD is a real-time voice activity detection system designed for
    enterprise use, providing accurate frame-level speech activity detection.
    It shows superior precision compared to both WebRTC VAD and Silero VAD.

    Pros:
    - Free and open-source (Apache 2.0)
    - Higher accuracy than Silero and WebRTC VAD
    - Very lightweight (~300KB library)
    - Fast speech-to-non-speech transition detection
    - No API key required

    Cons:
    - Requires libc++ on Linux (sudo apt install libc++1)
    - Only supports 16kHz sample rate
    - Newer/less tested than alternatives
    """

    # Module metadata for discovery
    name: ClassVar[str] = "TEN VAD"
    description: ClassVar[str] = (
        "High-performance voice activity detection from TEN Framework. "
        "Free, lightweight, and claims better accuracy than Silero VAD."
    )

    @classmethod
    def get_settings_schema(cls) -> List:
        """Return settings schema for TEN VAD configuration."""
        from strawberry.spoke_core.settings_schema import FieldType, SettingField

        return [
            SettingField(
                key="threshold",
                label="Speech Threshold",
                type=FieldType.NUMBER,
                default=0.5,
                min_value=0.0,
                max_value=1.0,
                description=(
                    "Probability threshold for speech detection (0.0 to 1.0). "
                    "Lower values = more sensitive, higher values = less false positives."
                ),
            ),
            SettingField(
                key="hop_size",
                label="Frame Size",
                type=FieldType.SELECT,
                default="256",
                options=["160", "256"],
                description=(
                    "Audio frame size in samples. "
                    "160 = 10ms frames, 256 = 16ms frames (default)."
                ),
            ),
        ]

    def __init__(
        self,
        sample_rate: int = 16000,
        threshold: float = 0.5,
        hop_size: int = 256,
    ):
        """Initialize TEN VAD.

        Args:
            sample_rate: Audio sample rate. TEN VAD requires 16000 Hz.
            threshold: Speech probability threshold (0.0 to 1.0)
            hop_size: Frame size in samples. Either 160 (10ms) or 256 (16ms).

        Raises:
            ImportError: If ten_vad is not installed
            OSError: If libc++ is not installed (Linux)
            ValueError: If sample_rate is not 16000
            ValueError: If hop_size is not 160 or 256
        """
        # TEN VAD only supports 16kHz
        if sample_rate != 16000:
            raise ValueError(
                f"TEN VAD requires 16000 Hz sample rate, got {sample_rate}"
            )

        # Validate hop_size
        hop_size = int(hop_size)  # Handle string from settings
        if hop_size not in (160, 256):
            raise ValueError(
                f"TEN VAD hop_size must be 160 or 256, got {hop_size}"
            )

        self._sample_rate = sample_rate
        self._threshold = threshold
        self._hop_size = hop_size
        self._last_probability = 0.0

        # Lazy load the model
        self._vad = None

    def _ensure_model(self) -> None:
        """Load TEN VAD model on first use."""
        if self._vad is not None:
            return

        from ten_vad import TenVad

        self._vad = TenVad(hop_size=self._hop_size, threshold=self._threshold)

    @property
    def frame_length(self) -> int:
        """Required audio frame length in samples.

        Returns the hop_size configured during initialization.
        """
        return self._hop_size

    @property
    def sample_rate(self) -> int:
        """Required audio sample rate (16000 Hz for TEN VAD)."""
        return self._sample_rate

    def is_speech(self, audio_frame: np.ndarray) -> bool:
        """Detect speech in audio frame.

        Args:
            audio_frame: Audio samples (int16), must be exactly hop_size samples

        Returns:
            True if speech probability >= threshold
        """
        prob = self.get_probability(audio_frame)
        return prob >= self._threshold

    def get_probability(self, audio_frame: np.ndarray) -> float:
        """Get speech probability for audio frame.

        Args:
            audio_frame: Audio samples (int16), must be exactly hop_size samples

        Returns:
            Probability of speech (0.0 to 1.0)
        """
        self._ensure_model()

        # TEN VAD expects int16 audio
        if audio_frame.dtype != np.int16:
            audio_frame = audio_frame.astype(np.int16)

        # Ensure correct shape
        audio_frame = np.squeeze(audio_frame)

        # Process the frame - returns (probability, flag)
        prob, _flag = self._vad.process(audio_frame)
        self._last_probability = prob
        return prob

    def preload(self) -> None:
        """Preload the TEN VAD model to avoid blocking the audio thread."""
        self._ensure_model()

    def cleanup(self) -> None:
        """Release TEN VAD resources.

        Note: TEN VAD uses __del__ for cleanup, so we just clear our reference.
        """
        self._vad = None
