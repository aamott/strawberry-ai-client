"""Orca TTS backend (Picovoice).

Requires: pip install pvorca
Also requires a Picovoice access key.
"""

import os
from typing import Iterator, List, Optional

import numpy as np

from ..base import AudioChunk, TTSEngine


class OrcaTTS(TTSEngine):
    """Text-to-Speech using Picovoice Orca.

    Orca is a streaming text-to-speech engine that:
    - Runs entirely on-device (no cloud API calls)
    - Supports streaming synthesis for low latency
    - Produces natural-sounding speech

    Pros:
    - Fast, offline operation
    - Streaming output for immediate playback
    - Natural voice quality

    Cons:
    - Requires Picovoice license
    - Limited voice options
    """

    # Module metadata for discovery
    name = "Orca (Picovoice)"
    description = "On-device text-to-speech using Picovoice Orca. Requires license key."

    @classmethod
    def get_settings_schema(cls) -> List:
        """Return settings schema for Orca TTS configuration."""
        from strawberry.core.settings_schema import FieldType, SettingField

        return [
            SettingField(
                key="access_key",
                label="Picovoice Access Key",
                type=FieldType.PASSWORD,
                secret=True,
                description="API key from Picovoice Console",
            ),
            SettingField(
                key="model_path",
                label="Custom Model Path",
                type=FieldType.TEXT,
                default="",
                description="Optional path to custom Orca model file",
            ),
        ]


    def __init__(
        self,
        access_key: Optional[str] = None,
        model_path: Optional[str] = None,
    ):
        """Initialize Orca TTS.

        Args:
            access_key: Picovoice access key. If None, reads from
                       PICOVOICE_API_KEY environment variable.
            model_path: Path to custom model file. If None, uses default.

        Raises:
            ImportError: If pvorca is not installed
            ValueError: If access_key is not provided
        """
        if access_key is None:
            access_key = os.environ.get("PICOVOICE_API_KEY")

        if not access_key:
            raise ValueError(
                "Picovoice access key required. Set PICOVOICE_API_KEY "
                "environment variable or pass access_key parameter."
            )

        import pvorca

        if model_path:
            self._orca = pvorca.create(
                access_key=access_key,
                model_path=model_path,
            )
        else:
            self._orca = pvorca.create(access_key=access_key)

        self._sample_rate_val = self._orca.sample_rate

    @property
    def sample_rate(self) -> int:
        return self._sample_rate_val

    def synthesize(self, text: str) -> AudioChunk:
        """Synthesize complete text to audio.

        Args:
            text: Text to synthesize

        Returns:
            Complete audio chunk
        """
        # Use non-streaming API for complete synthesis
        pcm, _ = self._orca.synthesize(text)
        audio = np.array(pcm, dtype=np.int16)

        return AudioChunk(audio=audio, sample_rate=self._sample_rate_val)

    def synthesize_stream(self, text: str) -> Iterator[AudioChunk]:
        """Synthesize with streaming output.

        Yields audio chunks as they're generated for low-latency playback.

        The Orca streaming API is designed for token-by-token synthesis from LLMs.
        For a complete text string, we feed it character by character or word by word.

        Args:
            text: Text to synthesize

        Yields:
            Audio chunks
        """
        stream = self._orca.stream_open()

        try:
            # Feed text to streaming synthesizer word by word
            # The stream buffers until it has enough context to synthesize
            words = text.split()
            for i, word in enumerate(words):
                # Add space before word (except first)
                chunk = word if i == 0 else " " + word
                pcm = stream.synthesize(chunk)
                if pcm is not None and len(pcm) > 0:
                    audio = np.array(pcm, dtype=np.int16)
                    yield AudioChunk(audio=audio, sample_rate=self._sample_rate_val)

            # Flush any remaining audio
            pcm = stream.flush()
            if pcm is not None and len(pcm) > 0:
                audio = np.array(pcm, dtype=np.int16)
                yield AudioChunk(audio=audio, sample_rate=self._sample_rate_val)

        finally:
            stream.close()

    def cleanup(self) -> None:
        """Release Orca resources."""
        if self._orca is not None:
            self._orca.delete()
            self._orca = None

