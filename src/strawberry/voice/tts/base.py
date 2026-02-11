"""Abstract base class for Text-to-Speech engines."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Dict, Iterator, List

import numpy as np


@dataclass
class AudioChunk:
    """Chunk of synthesized audio.

    Attributes:
        audio: Audio samples (int16)
        sample_rate: Sample rate in Hz
    """

    audio: np.ndarray
    sample_rate: int

    @property
    def duration_sec(self) -> float:
        """Duration of this chunk in seconds."""
        return len(self.audio) / self.sample_rate


class TTSEngine(ABC):
    """Abstract base class for Text-to-Speech engines.

    All TTS backends must implement this interface.

    To make a module discoverable and configurable via the settings UI,
    subclasses should define:
        - name: Human-readable name shown in UI dropdown
        - description: Help text for users
        - get_settings_schema(): Returns list of SettingField for configuration
    """

    # Module metadata for discovery (override in subclasses)
    name: ClassVar[str] = "Unnamed TTS"
    description: ClassVar[str] = ""

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Output audio sample rate in Hz."""
        pass

    @abstractmethod
    def synthesize(self, text: str) -> AudioChunk:
        """Synthesize complete text to audio.

        Args:
            text: Text to synthesize

        Returns:
            Complete audio chunk
        """
        pass

    @classmethod
    def get_settings_schema(cls) -> List[Any]:
        """Return the settings schema for this TTS provider.

        Override this method to define configurable settings for your TTS engine.
        Returns a list of SettingField objects.

        Default implementation returns empty list (no configurable settings).

        Returns:
            List of SettingField objects defining configurable options
        """
        return []

    @classmethod
    def is_healthy(cls) -> bool:
        """Check if this TTS backend can be used.

        Override this in subclasses to check for required dependencies,
        API keys, or other prerequisites. VoiceCore uses this to skip
        unhealthy backends during initialization.

        Returns:
            True if the backend is ready to use, False otherwise.
        """
        return True

    @classmethod
    def health_check_error(cls) -> str | None:
        """Return the error message if this backend is unhealthy.

        Override this in subclasses to provide a helpful error message
        when is_healthy() returns False.

        Returns:
            Error message string, or None if healthy.
        """
        return None

    @classmethod
    def get_default_settings(cls) -> Dict[str, Any]:
        """Return default values for all settings.

        Returns:
            Dictionary mapping setting keys to their default values
        """
        schema = cls.get_settings_schema()
        return {field.key: field.default for field in schema if hasattr(field, "key")}

    def synthesize_stream(self, text: str) -> Iterator[AudioChunk]:
        """Synthesize text with streaming output.

        Default implementation returns single chunk from synthesize().
        Override for backends with native streaming support.

        Args:
            text: Text to synthesize

        Yields:
            Audio chunks as they're generated
        """
        yield self.synthesize(text)

    def cleanup(self) -> None:
        """Release any resources held by the engine.

        Override in subclasses that need cleanup.
        """
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False
