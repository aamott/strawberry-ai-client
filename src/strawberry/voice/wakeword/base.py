"""Abstract base class for wake word detection."""

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Dict, List

import numpy as np


class WakeWordDetector(ABC):
    """Abstract base class for wake word detection.

    All wake word backends must implement this interface.

    To make a module discoverable and configurable via the settings UI,
    subclasses should define:
        - name: Human-readable name shown in UI dropdown
        - description: Help text for users
        - get_settings_schema(): Returns list of SettingField for configuration
    """

    # Module metadata for discovery (override in subclasses)
    name: ClassVar[str] = "Unnamed Wake Word"
    description: ClassVar[str] = ""

    @abstractmethod
    def __init__(self, keywords: List[str], sensitivity: float = 0.5):
        """Initialize the wake word detector.

        Args:
            keywords: List of wake words to detect
            sensitivity: Detection sensitivity (0.0 to 1.0)
                        Higher = more sensitive, more false positives
                        Lower = less sensitive, fewer false positives
        """
        pass

    @property
    @abstractmethod
    def keywords(self) -> List[str]:
        """List of wake words being detected."""
        pass

    @property
    @abstractmethod
    def frame_length(self) -> int:
        """Required audio frame length in samples."""
        pass

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Required audio sample rate in Hz."""
        pass

    @abstractmethod
    def process(self, audio_frame: np.ndarray) -> int:
        """Process an audio frame for wake word detection.

        Args:
            audio_frame: Audio samples (int16), must be frame_length samples

        Returns:
            Index of detected keyword (0-based), or -1 if none detected
        """
        pass

    @classmethod
    def get_settings_schema(cls) -> List[Any]:
        """Return the settings schema for this wake word provider.

        Override this method to define configurable settings.
        Returns a list of SettingField objects.
        """
        return []

    @classmethod
    def get_default_settings(cls) -> Dict[str, Any]:
        """Return default values for all settings."""
        schema = cls.get_settings_schema()
        return {field.key: field.default for field in schema if hasattr(field, 'key')}

    def cleanup(self) -> None:
        """Release any resources held by the detector.

        Override in subclasses that need cleanup.
        """
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False
