"""Silero VAD backend.

Requires: pip install torch
The model is downloaded on first use from torch.hub.
"""

import numpy as np

from ..base import VADBackend


class SileroVAD(VADBackend):
    """VAD using Silero model (runs locally, no API key needed).
    
    Silero VAD is a lightweight, accurate VAD model that runs
    entirely on CPU without needing external services.
    
    Pros:
    - Free, no API key needed
    - Fast (real-time capable)
    - Good accuracy
    
    Cons:
    - Requires PyTorch (large dependency)
    - First run downloads model (~3MB)
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        threshold: float = 0.5,
    ):
        """Initialize Silero VAD.
        
        Args:
            sample_rate: Audio sample rate (must be 8000 or 16000)
            threshold: Speech probability threshold (0.0 to 1.0)
            
        Raises:
            ImportError: If torch is not installed
            ValueError: If sample_rate is not 8000 or 16000
        """
        if sample_rate not in (8000, 16000):
            raise ValueError("Silero VAD only supports 8000 or 16000 Hz sample rates")

        self._sample_rate = sample_rate
        self._threshold = threshold
        self._last_probability = 0.0

        # Load model lazily to avoid import-time torch dependency
        self._model = None
        self._utils = None

    def _ensure_model(self):
        """Load model on first use."""
        if self._model is not None:
            return

        import torch

        # Load Silero VAD from torch.hub
        self._model, self._utils = torch.hub.load(
            repo_or_dir='snakers4/silero-vad',
            model='silero_vad',
            force_reload=False,
            trust_repo=True,
        )
        self._model.eval()

    def is_speech(self, audio_frame: np.ndarray) -> bool:
        """Detect speech in audio frame.
        
        Args:
            audio_frame: Audio samples (int16)
            
        Returns:
            True if speech probability >= threshold
        """
        prob = self.get_probability(audio_frame)
        return prob >= self._threshold

    def get_probability(self, audio_frame: np.ndarray) -> float:
        """Get speech probability for audio frame.
        
        Args:
            audio_frame: Audio samples (int16)
            
        Returns:
            Probability of speech (0.0 to 1.0)
        """
        self._ensure_model()

        import torch

        # Convert int16 to float32 and normalize to [-1, 1]
        audio = audio_frame.astype(np.float32) / 32768.0
        tensor = torch.from_numpy(audio)

        with torch.no_grad():
            prob = self._model(tensor, self._sample_rate).item()

        self._last_probability = prob
        return prob

    def cleanup(self) -> None:
        """Release model resources."""
        self._model = None
        self._utils = None

