"""Voice configuration.

This module contains the configuration dataclasses for VoiceCore and its components.
"""

from dataclasses import dataclass, field
from typing import List, Sequence


@dataclass
class VoiceConfig:
    """Configuration for VoiceCore.

    Attributes:
        wake_words: List of wake word phrases to detect.
        sensitivity: Wake word detection sensitivity (0.0-1.0).
        sample_rate: Audio sample rate in Hz.
        audio_feedback_enabled: Whether to play audio feedback sounds.
        stt_backend: Speech-to-text backend module name.
        tts_backend: Text-to-speech backend module name.
        vad_backend: Voice activity detection backend module name.
        wake_backend: Wake word detection backend module name.
    """

    wake_words: List[str] = field(default_factory=lambda: ["hey barista"])
    sensitivity: float = 0.5
    sample_rate: int = 16000
    audio_feedback_enabled: bool = True

    # Backend selection (module names). Each value supports ordered fallback:
    # - A single backend name (e.g. "leopard")
    # - A comma-separated string (e.g. "leopard,google,mock")
    # - A list of backend names (e.g. ["leopard", "google", "mock"])
    stt_backend: str | Sequence[str] = "leopard"
    tts_backend: str | Sequence[str] = "pocket"
    vad_backend: str | Sequence[str] = "silero"
    wake_backend: str | Sequence[str] = "porcupine"
