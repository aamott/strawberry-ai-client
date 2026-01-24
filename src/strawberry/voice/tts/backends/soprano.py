"""Soprano TTS backend.

Requires:
    pip install soprano-tts
    pip uninstall -y torch  # Remove existing torch
    pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cu126

Also requires a CUDA-enabled GPU (CPU support planned).

Soprano is an ultra-fast, lightweight TTS model with streaming support.
- 80M parameters, ~2000x real-time factor
- 32 kHz high-fidelity output
- <15ms streaming latency
- <1 GB VRAM

See: https://sopranotts.com/
"""

import logging
from typing import ClassVar, Iterator, List

import numpy as np

from ..base import AudioChunk, TTSEngine

logger = logging.getLogger(__name__)


class SopranoTTS(TTSEngine):
    """Text-to-Speech using Soprano TTS.

    Soprano is an ultra-fast, lightweight text-to-speech model:
    - Only 80M parameters
    - ~2000x real-time factor (10 hours of audio in <20 seconds)
    - 32 kHz high-fidelity output
    - <15ms latency for first audio chunk with streaming
    - Uses <1 GB VRAM

    Pros:
    - Extremely fast inference
    - Low latency streaming
    - High quality output (32 kHz)
    - Open source / free

    Cons:
    - Requires CUDA GPU (CPU support planned)
    - Requires PyTorch with CUDA
    """

    # Module metadata for discovery
    name: ClassVar[str] = "Soprano TTS"
    description: ClassVar[str] = (
        "Ultra-fast, lightweight TTS with streaming. "
        "Requires CUDA GPU. Free and open source."
    )

    # Soprano outputs at 32 kHz
    SAMPLE_RATE: ClassVar[int] = 32000

    @classmethod
    def get_settings_schema(cls) -> List:
        """Return settings schema for Soprano TTS configuration."""
        from strawberry.shared.settings import FieldType, SettingField

        return [
            SettingField(
                key="backend",
                label="Inference Backend",
                type=FieldType.SELECT,
                options=["auto", "lmdeploy", "hf"],
                default="auto",
                description=(
                    "Inference backend. 'auto' uses LMDeploy if available "
                    "(faster), falls back to HuggingFace transformers."
                ),
            ),
            SettingField(
                key="device",
                label="Device",
                type=FieldType.SELECT,
                options=["cuda", "cuda:0", "cuda:1"],
                default="cuda",
                description="CUDA device for inference. CPU not yet supported.",
            ),
        ]

    def __init__(
        self,
        backend: str = "auto",
        device: str = "cuda",
    ):
        """Initialize Soprano TTS.

        Args:
            backend: Inference backend - 'auto', 'lmdeploy', or 'hf'.
                    'auto' tries LMDeploy first, then falls back to HF.
            device: CUDA device (e.g., 'cuda', 'cuda:0', 'cuda:1').
                   CPU is not yet supported by Soprano.

        Raises:
            ImportError: If soprano-tts is not installed
            RuntimeError: If CUDA is not available
        """
        self._backend = backend
        self._device = device

        # Lazy load the model
        self._model = None

    def _ensure_model(self) -> None:
        """Load model on first use."""
        if self._model is not None:
            return

        try:
            from soprano import SopranoTTS as SopranoModel
        except ImportError as e:
            raise ImportError(
                "soprano-tts not installed. Install with:\n"
                "  pip install soprano-tts\n"
                "  pip uninstall -y torch\n"
                "  pip install torch==2.8.0 --index-url "
                "https://download.pytorch.org/whl/cu126"
            ) from e

        # Check CUDA availability
        try:
            import torch

            if not torch.cuda.is_available():
                raise RuntimeError(
                    "Soprano TTS requires CUDA but no GPU was detected. "
                    "Ensure you have a CUDA-enabled GPU and proper drivers."
                )
        except ImportError as e:
            raise ImportError("PyTorch not installed") from e

        logger.info(
            f"Loading Soprano TTS model (backend={self._backend}, device={self._device})"
        )
        self._model = SopranoModel(backend=self._backend, device=self._device)
        logger.info("Soprano TTS model loaded successfully")

    @property
    def sample_rate(self) -> int:
        """Output sample rate (32 kHz for Soprano)."""
        return self.SAMPLE_RATE

    def synthesize(self, text: str) -> AudioChunk:
        """Synthesize complete text to audio.

        Args:
            text: Text to synthesize

        Returns:
            Complete audio chunk at 32 kHz
        """
        if not text or not text.strip():
            return AudioChunk(
                audio=np.array([], dtype=np.int16), sample_rate=self.SAMPLE_RATE
            )

        self._ensure_model()

        # Soprano returns audio as numpy array or saves to file
        # When no output path is given, returns the audio directly
        audio = self._model.infer(text)

        # Convert to int16 if needed (Soprano may return float32)
        if audio.dtype == np.float32 or audio.dtype == np.float64:
            # Normalize to int16 range
            audio = (audio * 32767).astype(np.int16)
        elif audio.dtype != np.int16:
            audio = audio.astype(np.int16)

        return AudioChunk(audio=audio, sample_rate=self.SAMPLE_RATE)

    def synthesize_stream(self, text: str) -> Iterator[AudioChunk]:
        """Synthesize with streaming output for low-latency playback.

        Soprano supports streaming synthesis with <15ms first-chunk latency.

        Args:
            text: Text to synthesize

        Yields:
            Audio chunks as they're generated
        """
        if not text or not text.strip():
            return

        self._ensure_model()

        # Check if streaming is available
        if hasattr(self._model, "infer_stream"):
            # Use native streaming API
            for chunk in self._model.infer_stream(text):
                if chunk is not None and len(chunk) > 0:
                    # Convert to int16 if needed
                    if chunk.dtype == np.float32 or chunk.dtype == np.float64:
                        chunk = (chunk * 32767).astype(np.int16)
                    elif chunk.dtype != np.int16:
                        chunk = chunk.astype(np.int16)

                    yield AudioChunk(audio=chunk, sample_rate=self.SAMPLE_RATE)
        else:
            # Fallback: synthesize in sentence chunks for pseudo-streaming
            # This provides some latency reduction for longer texts
            sentences = self._split_into_sentences(text)

            for sentence in sentences:
                if sentence.strip():
                    audio = self._model.infer(sentence)

                    # Convert to int16 if needed
                    if audio.dtype == np.float32 or audio.dtype == np.float64:
                        audio = (audio * 32767).astype(np.int16)
                    elif audio.dtype != np.int16:
                        audio = audio.astype(np.int16)

                    yield AudioChunk(audio=audio, sample_rate=self.SAMPLE_RATE)

    def _split_into_sentences(self, text: str) -> List[str]:
        """Split text into sentences for pseudo-streaming.

        Args:
            text: Text to split

        Returns:
            List of sentences
        """
        import re

        # Split on sentence-ending punctuation while keeping the punctuation
        pattern = r"(?<=[.!?])\s+"
        sentences = re.split(pattern, text)
        return [s.strip() for s in sentences if s.strip()]

    def preload(self) -> None:
        """Preload the model to avoid blocking on first synthesis."""
        self._ensure_model()

    def cleanup(self) -> None:
        """Release model resources."""
        if self._model is not None:
            # Clear model reference to allow garbage collection
            self._model = None

            # Explicitly clear CUDA cache
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass
