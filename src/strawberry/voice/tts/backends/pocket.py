"""Pocket-TTS backend (Kyutai Labs).

Requires: pip install pocket-tts
A lean, CPU-efficient TTS system with voice cloning via audio prompts.

https://github.com/kyutai-labs/pocket-tts
"""

from typing import Iterator, List, Optional

import numpy as np

from ..base import AudioChunk, TTSEngine

# Check for pocket-tts availability at module load time
_POCKET_AVAILABLE = False
_POCKET_IMPORT_ERROR: str | None = None
try:
    from pocket_tts import TTSModel  # noqa: F401

    _POCKET_AVAILABLE = True
except ImportError as e:
    _POCKET_IMPORT_ERROR = (
        f"pocket-tts not installed. Install with: pip install pocket-tts. ({e})"
    )


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
    """

    # Module metadata for discovery
    name = "Pocket-TTS (Kyutai)"
    description = (
        "Lightweight on-device TTS with voice cloning support. No API key required."
    )

    # Class-level cache for model and voice state
    _cached_model = None
    _cached_voice_state = None
    _cached_voice_prompt_path = None

    @classmethod
    def is_healthy(cls) -> bool:
        """Check if Pocket-TTS is available.

        Returns:
            True if pocket-tts package is installed, False otherwise.
        """
        return _POCKET_AVAILABLE

    @classmethod
    def health_check_error(cls) -> str | None:
        """Return the error message if Pocket-TTS is not available.

        Returns:
            Error message if pocket-tts is not installed, None otherwise.
        """
        return _POCKET_IMPORT_ERROR

    @classmethod
    def get_settings_schema(cls) -> List:
        """Return settings schema for Pocket-TTS configuration."""
        from strawberry.shared.settings import FieldType, SettingField

        return [
            SettingField(
                key="voice_prompt_path",
                label="Voice Prompt Audio",
                type=FieldType.TEXT,
                default="alba",
                description=(
                    "Voice selection. Provide a built-in voice name (e.g. 'alba') "
                    "or a path/URL to an audio prompt for voice cloning. "
                    "For HuggingFace prompts, use 'hf://...'."
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
                              Default: a built-in catalog voice ("alba").

        Raises:
            ImportError: If pocket-tts is not installed
        """
        from pocket_tts import TTSModel

        # Use built-in voice by default to avoid gated voice-cloning weights.
        if voice_prompt_path is None:
            voice_prompt_path = "alba"

        # Load model (cached at class level)
        if PocketTTS._cached_model is None:
            import logging

            logger = logging.getLogger(__name__)
            logger.info("Loading Pocket-TTS model (this may take a few seconds)...")
            PocketTTS._cached_model = TTSModel.load_model()
            logger.info("Pocket-TTS model loaded")

        self._model = PocketTTS._cached_model

        # Load voice state (cache if same selection)
        if (
            PocketTTS._cached_voice_state is None
            or PocketTTS._cached_voice_prompt_path != voice_prompt_path
        ):
            import logging

            logger = logging.getLogger(__name__)

            # If it looks like a file/URL, treat it as an audio prompt for voice cloning.
            # Otherwise treat it as a built-in catalog voice name.
            is_audio_prompt = (
                "://" in voice_prompt_path
                or voice_prompt_path.endswith(".wav")
                or voice_prompt_path.endswith(".mp3")
            )

            if not is_audio_prompt and hasattr(self._model, "get_state_for_voice"):
                logger.info(f"Loading Pocket-TTS built-in voice: {voice_prompt_path}")
                PocketTTS._cached_voice_state = self._model.get_state_for_voice(
                    voice_prompt_path
                )
                PocketTTS._cached_voice_prompt_path = voice_prompt_path
                logger.info("Built-in voice loaded")
            else:
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
        """Synthesize with streaming output using native pocket-tts streaming.

        Uses ``generate_audio_stream()`` which yields audio tensors as each
        frame (~80 ms) is decoded by the Mimi codec, allowing playback to
        start almost immediately instead of waiting for the full utterance.

        Args:
            text: Text to synthesize

        Yields:
            Audio chunks as they are decoded (typically ~80 ms each).
        """
        for audio_tensor in self._model.generate_audio_stream(self._voice_state, text):
            audio = (audio_tensor.numpy() * 32767).astype(np.int16)
            if len(audio) > 0:
                yield AudioChunk(audio=audio, sample_rate=self._sample_rate_val)

    def cleanup(self) -> None:
        """Release resources.

        Note: Model and voice state are cached at class level,
        so we don't actually clean them up here.
        """
        pass


if __name__ == "__main__":
    from dotenv import load_dotenv

    from strawberry.utils.paths import get_project_root
    from strawberry.voice.audio.playback import AudioPlayer

    load_dotenv(get_project_root() / ".env", override=True)

    cls = PocketTTS
    print("backend=pocket", "healthy=", cls.is_healthy())
    if not cls.is_healthy():
        print("health_error=", cls.health_check_error())
        raise SystemExit(1)

    tts = cls()
    text = "Hello from Pocket TTS. If you hear this, Pocket playback works."
    chunk = tts.synthesize(text)
    print("samples=", len(chunk.audio), "sample_rate=", chunk.sample_rate)
    if len(chunk.audio) == 0:
        raise SystemExit("Pocket produced empty audio")
    AudioPlayer(sample_rate=chunk.sample_rate).play(
        chunk.audio,
        sample_rate=chunk.sample_rate,
        blocking=True,
    )
