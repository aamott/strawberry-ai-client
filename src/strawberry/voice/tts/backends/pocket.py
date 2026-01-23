"""Pocket-TTS backend (Kyutai Labs).

Requires: pip install pocket-tts
A lean, CPU-efficient TTS system with voice cloning via audio prompts.
"""

from typing import Iterator, List, Optional

import numpy as np

from ..base import AudioChunk, TTSEngine


class PocketTTS(TTSEngine):
    """Text-to-Speech using Kyutai Labs Pocket-TTS.

    Pocket-TTS is a lightweight TTS model that:
    - Runs entirely on-device (no cloud API calls)
    - Supports voice cloning via audio prompts
    - Optimized for CPU inference
    - Natural-sounding speech

    Pros:
    - Fast CPU operation
    - Voice cloning from audio samples
    - Open source, no API keys required
    - Small model size (~100MB)

    Cons:
    - Model loading is slow (~few seconds)
    - Voice prompt initialization is slow
    - No native streaming support
    """

    # Module metadata for discovery
    name = "Pocket-TTS (Kyutai)"
    description = "Lightweight on-device TTS with voice cloning support. No API key required."

    # Class-level cache for model and voice state
    _cached_model = None
    _cached_voice_state = None
    _cached_voice_prompt_path = None

    @classmethod
    def get_settings_schema(cls) -> List:
        """Return settings schema for Pocket-TTS configuration."""
        from strawberry.spoke_core.settings_schema import FieldType, SettingField

        return [
            SettingField(
                key="voice_prompt_path",
                label="Voice Prompt Audio",
                type=FieldType.TEXT,
                default="hf://kyutai/tts-voices/alba-mackenna/casual.wav",
                description=(
                    "Path to audio file for voice cloning. "
                    "Use 'hf://kyutai/tts-voices/...' for HuggingFace voices "
                    "or local file path."
                ),
            ),
        ]

    def __init__(
        self,
        voice_prompt_path: Optional[str] = None,
    ):
        """Initialize Pocket-TTS.

        Args:
            voice_prompt_path: Path to voice prompt audio file.
                              Supports HuggingFace URLs (hf://...) or local paths.
                              Default: alba-mackenna casual voice from HF.

        Raises:
            ImportError: If pocket-tts is not installed
        """
        from pocket_tts import TTSModel

        # Use default voice if not specified
        if voice_prompt_path is None:
            voice_prompt_path = "hf://kyutai/tts-voices/alba-mackenna/casual.wav"

        # Load model (cached at class level)
        if PocketTTS._cached_model is None:
            import logging
            logger = logging.getLogger(__name__)
            logger.info("Loading Pocket-TTS model (this may take a few seconds)...")
            PocketTTS._cached_model = TTSModel.load_model()
            logger.info("Pocket-TTS model loaded")

        self._model = PocketTTS._cached_model

        # Load voice state (cache if same prompt)
        if (
            PocketTTS._cached_voice_state is None
            or PocketTTS._cached_voice_prompt_path != voice_prompt_path
        ):
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"Loading voice prompt: {voice_prompt_path}")
            PocketTTS._cached_voice_state = self._model.get_state_for_audio_prompt(
                voice_prompt_path
            )
            PocketTTS._cached_voice_prompt_path = voice_prompt_path
            logger.info("Voice prompt loaded")

        self._voice_state = PocketTTS._cached_voice_state
        self._sample_rate_val = self._model.sample_rate

    @property
    def sample_rate(self) -> int:
        """Output sample rate."""
        return self._sample_rate_val

    def synthesize(self, text: str) -> AudioChunk:
        """Synthesize complete text to audio.

        Args:
            text: Text to synthesize

        Returns:
            Complete audio chunk with PCM data
        """
        # Generate audio (returns 1D torch tensor with PCM data)
        audio_tensor = self._model.generate_audio(self._voice_state, text)

        # Convert to numpy int16
        audio = (audio_tensor.numpy() * 32767).astype(np.int16)

        return AudioChunk(audio=audio, sample_rate=self._sample_rate_val)

    def synthesize_stream(self, text: str) -> Iterator[AudioChunk]:
        """Synthesize with streaming output.

        Note: Pocket-TTS doesn't support native streaming, so this
        yields a single chunk from synthesize().

        Args:
            text: Text to synthesize

        Yields:
            Single audio chunk
        """
        yield self.synthesize(text)

    def cleanup(self) -> None:
        """Release resources.

        Note: Model and voice state are cached at class level,
        so we don't actually clean them up here.
        """
        pass
