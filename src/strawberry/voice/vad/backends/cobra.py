"""Picovoice Cobra VAD backend.

Requires: pip install pvcobra
Also requires a Picovoice access key from https://picovoice.ai/
"""

import os
from typing import ClassVar, List, Optional

import numpy as np

from ..base import VADBackend


class CobraVAD(VADBackend):
    """VAD using Picovoice Cobra (on-device, deep learning powered).

    Cobra is a highly-accurate and lightweight voice activity detection
    engine that runs entirely on-device without needing external services.

    Pros:
    - Highly accurate (deep learning powered)
    - Fast (real-time capable on CPU)
    - Lightweight (~3MB library)
    - No internet required after setup

    Cons:
    - Requires Picovoice access key (free tier available)
    - Commercial use requires paid license
    """

    # Module metadata for discovery
    name: ClassVar[str] = "Cobra (Picovoice)"
    description: ClassVar[str] = (
        "On-device voice activity detection using Picovoice Cobra. "
        "Highly accurate and lightweight. Requires license key."
    )

    @classmethod
    def get_settings_schema(cls) -> List:
        """Return settings schema for Cobra configuration."""
        from strawberry.shared.settings import FieldType, SettingField

        return [
            SettingField(
                key="access_key",
                label="Picovoice Access Key",
                type=FieldType.PASSWORD,
                secret=True,
                env_key="PICOVOICE_API_KEY",
                description=(
                    "API key from Picovoice Console. "
                    "Same key works for Porcupine, Leopard, Orca, etc."
                ),
            ),
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
        ]

    def __init__(
        self,
        sample_rate: int = 16000,
        threshold: float = 0.5,
        access_key: Optional[str] = None,
    ):
        """Initialize Cobra VAD.

        Args:
            sample_rate: Audio sample rate. Cobra requires 16000 Hz.
            threshold: Speech probability threshold (0.0 to 1.0)
            access_key: Picovoice access key. If None, reads from
                       PICOVOICE_API_KEY environment variable.

        Raises:
            ImportError: If pvcobra is not installed
            ValueError: If sample_rate is not 16000
            ValueError: If access_key is not provided and not in environment
        """
        # Cobra only supports 16kHz
        if sample_rate != 16000:
            raise ValueError(
                f"Cobra VAD requires 16000 Hz sample rate, got {sample_rate}"
            )

        self._sample_rate = sample_rate
        self._threshold = threshold
        self._last_probability = 0.0

        # Resolve access key
        if not access_key:
            access_key = os.environ.get("PICOVOICE_API_KEY")

        if not access_key:
            raise ValueError(
                "Picovoice access key required. Set PICOVOICE_API_KEY "
                "environment variable or pass access_key parameter."
            )

        self._access_key = access_key

        # Lazy load the model
        self._cobra = None

    def _ensure_model(self) -> None:
        """Load Cobra model on first use."""
        if self._cobra is not None:
            return

        import pvcobra

        self._cobra = pvcobra.create(access_key=self._access_key)

    @property
    def frame_length(self) -> int:
        """Required audio frame length in samples.

        Cobra requires a specific frame size for processing.
        """
        self._ensure_model()
        return self._cobra.frame_length

    @property
    def sample_rate(self) -> int:
        """Required audio sample rate (16000 Hz for Cobra)."""
        return self._sample_rate

    def is_speech(self, audio_frame: np.ndarray) -> bool:
        """Detect speech in audio frame.

        Args:
            audio_frame: Audio samples (int16), should be exactly frame_length samples

        Returns:
            True if speech probability >= threshold
        """
        prob = self.get_probability(audio_frame)
        return prob >= self._threshold

    def get_probability(self, audio_frame: np.ndarray) -> float:
        """Get speech probability for audio frame.

        Args:
            audio_frame: Audio samples (int16), should be exactly frame_length samples

        Returns:
            Probability of speech (0.0 to 1.0)
        """
        self._ensure_model()

        # Cobra expects int16 audio
        if audio_frame.dtype != np.int16:
            audio_frame = audio_frame.astype(np.int16)

        # Process the frame
        prob = self._cobra.process(audio_frame)
        self._last_probability = prob
        return prob

    def preload(self) -> None:
        """Preload the Cobra model to avoid blocking the audio thread."""
        self._ensure_model()

    def cleanup(self) -> None:
        """Release Cobra resources."""
        if self._cobra is not None:
            self._cobra.delete()
            self._cobra = None
