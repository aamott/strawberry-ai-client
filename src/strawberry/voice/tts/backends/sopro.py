"""Sopro TTS backend with zero-shot voice cloning.

Requires:
    pip install sopro

Optionally for best performance on Apple Silicon:
    pip install torch==2.6.0  # Without torchvision for ~3x speedup

Sopro is a lightweight English TTS model with voice cloning.
- 169M parameters
- 0.25 RTF on CPU (30s audio in 7.5s on M3)
- Streaming support
- Zero-shot voice cloning with 3-12s reference audio

See: https://github.com/samuel-vitorino/sopro
"""

import logging
from typing import ClassVar, Iterator, List, Optional

import numpy as np

from ..base import AudioChunk, TTSEngine

logger = logging.getLogger(__name__)

# Check for sopro availability at module load time
_SOPRO_AVAILABLE = False
_SOPRO_IMPORT_ERROR: str | None = None
try:
    import sopro  # noqa: F401
    _SOPRO_AVAILABLE = True
except ImportError as e:
    _SOPRO_IMPORT_ERROR = f"sopro not installed. Install with: pip install sopro. ({e})"


class SoproTTS(TTSEngine):
    """Text-to-Speech using Sopro with zero-shot voice cloning.

    Sopro (Portuguese for "breath/blow") is a lightweight English TTS model
    that supports zero-shot voice cloning using reference audio.

    Architecture uses dilated convolutions (WaveNet-style) and lightweight
    cross-attention layers instead of Transformers.

    Pros:
    - Runs on CPU (0.25 RTF on M3)
    - Zero-shot voice cloning
    - Streaming support
    - Open source / free (Apache 2.0)

    Cons:
    - English only
    - Voice cloning quality depends on reference audio quality
    - Max ~32 seconds per generation
    - Can be inconsistent; may need parameter tuning
    """

    # Module metadata for discovery
    name: ClassVar[str] = "Sopro TTS"
    description: ClassVar[str] = (
        "Lightweight TTS with zero-shot voice cloning. "
        "Runs on CPU. Free and open source."
    )

    # Sopro uses Mimi codec, outputs 24kHz
    SAMPLE_RATE: ClassVar[int] = 24000

    @classmethod
    def is_healthy(cls) -> bool:
        """Check if Sopro TTS is available.

        Returns:
            True if sopro package is installed, False otherwise.
        """
        return _SOPRO_AVAILABLE

    @classmethod
    def health_check_error(cls) -> str | None:
        """Return the error message if Sopro is not available.

        Returns:
            Error message if sopro is not installed, None otherwise.
        """
        return _SOPRO_IMPORT_ERROR

    @classmethod
    def get_settings_schema(cls) -> List:
        """Return settings schema for Sopro TTS configuration."""
        from strawberry.shared.settings import FieldType, SettingField

        return [
            SettingField(
                key="device",
                label="Device",
                type=FieldType.SELECT,
                options=["cpu", "cuda", "cuda:0", "cuda:1", "mps"],
                default="cpu",
                description="Device for inference. CPU works well, GPU is faster.",
            ),
            SettingField(
                key="ref_audio_path",
                label="Reference Audio Path",
                type=FieldType.TEXT,
                default="",
                description=(
                    "Path to reference audio for voice cloning (3-12 seconds). "
                    "Leave empty to use default voice."
                ),
            ),
            SettingField(
                key="temperature",
                label="Temperature",
                type=FieldType.NUMBER,
                default=1.0,
                min_value=0.1,
                max_value=2.0,
                description="Sampling temperature. Higher = more variation.",
            ),
            SettingField(
                key="top_p",
                label="Top P",
                type=FieldType.NUMBER,
                default=0.95,
                min_value=0.1,
                max_value=1.0,
                description="Nucleus sampling threshold.",
            ),
            SettingField(
                key="style_strength",
                label="Style Strength",
                type=FieldType.NUMBER,
                default=1.0,
                min_value=0.0,
                max_value=2.0,
                description=(
                    "FiLM strength for voice cloning. "
                    "Adjust to improve/reduce voice similarity."
                ),
            ),
        ]

    def __init__(
        self,
        device: str = "cpu",
        ref_audio_path: Optional[str] = None,
        temperature: float = 1.0,
        top_p: float = 0.95,
        style_strength: float = 1.0,
    ):
        """Initialize Sopro TTS.

        Args:
            device: Device for inference ('cpu', 'cuda', 'mps').
            ref_audio_path: Path to reference audio for voice cloning (3-12s).
                           If None or empty, uses default voice.
            temperature: Sampling temperature (default 1.0).
            top_p: Nucleus sampling threshold (default 0.95).
            style_strength: FiLM strength for voice cloning (default 1.0).

        Raises:
            ImportError: If sopro is not installed
        """
        self._device = device
        self._ref_audio_path = ref_audio_path if ref_audio_path else None
        self._temperature = temperature
        self._top_p = top_p
        self._style_strength = style_strength

        # Lazy load the model
        self._model = None

    def _ensure_model(self) -> None:
        """Load model on first use."""
        if self._model is not None:
            return

        try:
            from sopro import SoproTTS as SoproModel
        except ImportError as e:
            raise ImportError(
                "sopro not installed. Install with: pip install sopro"
            ) from e

        logger.info(f"Loading Sopro TTS model (device={self._device})")
        self._model = SoproModel.from_pretrained(
            "samuel-vitorino/sopro", device=self._device
        )
        logger.info("Sopro TTS model loaded successfully")

    @property
    def sample_rate(self) -> int:
        """Output sample rate (24 kHz for Sopro)."""
        return self.SAMPLE_RATE

    def synthesize(self, text: str) -> AudioChunk:
        """Synthesize complete text to audio.

        Args:
            text: Text to synthesize

        Returns:
            Complete audio chunk at 24 kHz
        """
        if not text or not text.strip():
            return AudioChunk(
                audio=np.array([], dtype=np.int16), sample_rate=self.SAMPLE_RATE
            )

        self._ensure_model()

        # Build synthesis kwargs
        kwargs = {
            "temperature": self._temperature,
            "top_p": self._top_p,
            "style_strength": self._style_strength,
        }
        if self._ref_audio_path:
            kwargs["ref_audio_path"] = self._ref_audio_path

        # Synthesize (returns torch tensor)
        wav = self._model.synthesize(text, **kwargs)

        # Convert torch tensor to numpy int16
        audio = self._tensor_to_int16(wav)

        return AudioChunk(audio=audio, sample_rate=self.SAMPLE_RATE)

    def synthesize_stream(self, text: str) -> Iterator[AudioChunk]:
        """Synthesize with streaming output for low-latency playback.

        Note: Streaming version is not bit-exact with non-streaming.
        For best quality, use synthesize() instead.

        Args:
            text: Text to synthesize

        Yields:
            Audio chunks as they're generated
        """
        if not text or not text.strip():
            return

        self._ensure_model()

        # Build synthesis kwargs
        kwargs = {
            "temperature": self._temperature,
            "top_p": self._top_p,
            "style_strength": self._style_strength,
        }
        if self._ref_audio_path:
            kwargs["ref_audio_path"] = self._ref_audio_path

        # Stream synthesis
        for chunk in self._model.stream(text, **kwargs):
            if chunk is not None and chunk.numel() > 0:
                # Move to CPU and convert to int16
                audio = self._tensor_to_int16(chunk.cpu())
                yield AudioChunk(audio=audio, sample_rate=self.SAMPLE_RATE)

    def _tensor_to_int16(self, tensor) -> np.ndarray:
        """Convert torch tensor to numpy int16 array.

        Args:
            tensor: PyTorch tensor (float32, range [-1, 1])

        Returns:
            Numpy array of int16 samples
        """
        # Detach and convert to numpy
        audio = tensor.detach().cpu().numpy()

        # Flatten if needed (remove batch/channel dims)
        audio = audio.squeeze()

        # Normalize float to int16 range
        if audio.dtype in (np.float32, np.float64):
            # Clip to [-1, 1] and scale to int16
            audio = np.clip(audio, -1.0, 1.0)
            audio = (audio * 32767).astype(np.int16)
        elif audio.dtype != np.int16:
            audio = audio.astype(np.int16)

        return audio

    def set_reference_audio(self, path: str) -> None:
        """Set reference audio for voice cloning.

        Args:
            path: Path to reference audio file (3-12 seconds recommended)
        """
        self._ref_audio_path = path if path else None

    def preload(self) -> None:
        """Preload the model to avoid blocking on first synthesis."""
        self._ensure_model()

    def cleanup(self) -> None:
        """Release model resources."""
        if self._model is not None:
            self._model = None

            # Clear CUDA/MPS cache if applicable
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                elif hasattr(torch, "mps") and torch.backends.mps.is_available():
                    # MPS doesn't have empty_cache, but we can sync
                    pass
            except ImportError:
                pass


if __name__ == "__main__":
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    from strawberry.utils.paths import get_project_root
    from strawberry.voice.audio.playback import AudioPlayer

    load_dotenv(get_project_root() / ".env", override=True)

    cls = SoproTTS
    print("backend=sopro", "healthy=", cls.is_healthy())
    if not cls.is_healthy():
        print("health_error=", cls.health_check_error())
        raise SystemExit(1)

    ref = os.environ.get("SOPRO_REF_AUDIO")
    if ref:
        ref_path = Path(ref)
    else:
        ref_path = Path("tests") / "assets" / "myvoice.wav"

    if not ref_path.exists():
        raise SystemExit(
            "Sopro requires reference audio. Provide tests/assets/myvoice.wav "
            "or set SOPRO_REF_AUDIO=/path/to/ref.wav"
        )

    tts = cls(ref_audio_path=str(ref_path))
    text = "Hello from Sopro TTS. If you hear this, Sopro playback works."
    chunk = tts.synthesize(text)
    print("samples=", len(chunk.audio), "sample_rate=", chunk.sample_rate)
    if len(chunk.audio) == 0:
        raise SystemExit("Sopro produced empty audio")
    AudioPlayer(sample_rate=chunk.sample_rate).play(
        chunk.audio,
        sample_rate=chunk.sample_rate,
        blocking=True,
    )
