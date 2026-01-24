"""Abstract base class for Voice Activity Detection backends."""

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Dict, List

import numpy as np


class VADBackend(ABC):
    """Abstract base class for Voice Activity Detection.

    All VAD backends must implement this interface to be pluggable.

    To make a module discoverable and configurable via the settings UI,
    subclasses should define:
        - name: Human-readable name shown in UI dropdown
        - description: Help text for users
        - get_settings_schema(): Returns list of SettingField for configuration
    """

    # Module metadata for discovery (override in subclasses)
    name: ClassVar[str] = "Unnamed VAD"
    description: ClassVar[str] = ""

    @abstractmethod
    def __init__(self, sample_rate: int = 16000):
        """Initialize the VAD backend.

        Args:
            sample_rate: Expected audio sample rate in Hz
        """
        pass

    @abstractmethod
    def is_speech(self, audio_frame: np.ndarray) -> bool:
        """Determine if audio frame contains speech.

        Args:
            audio_frame: Audio samples (int16)

        Returns:
            True if speech detected, False otherwise
        """
        pass

    @abstractmethod
    def get_probability(self, audio_frame: np.ndarray) -> float:
        """Get speech probability for audio frame.

        Args:
            audio_frame: Audio samples (int16)

        Returns:
            Probability of speech (0.0 to 1.0)
        """
        pass

    @classmethod
    def get_settings_schema(cls) -> List[Any]:
        """Return the settings schema for this VAD provider.

        Override this method to define configurable settings.
        Returns a list of SettingField objects.
        """
        return []

    @classmethod
    def get_default_settings(cls) -> Dict[str, Any]:
        """Return default values for all settings."""
        schema = cls.get_settings_schema()
        return {field.key: field.default for field in schema if hasattr(field, 'key')}

    def preload(self) -> None:
        """Preload any models or resources needed for inference.

        Call this during initialization to avoid blocking the audio thread
        on the first is_speech() call. Override in subclasses that lazy-load.
        """
        pass

    def cleanup(self) -> None:
        """Release any resources held by the backend.

        Override in subclasses that need cleanup.
        """
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False
