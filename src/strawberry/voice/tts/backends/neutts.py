"""NeuTTS backend.

Install options:
- pip install neutts
- pip install "neutts @ git+https://github.com/neuphonic/neutts.git"
Project: https://github.com/neuphonic/neutts
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar, Iterator, List

import numpy as np

from ..base import AudioChunk, TTSEngine

_NEUTTS_AVAILABLE = False
_NEUTTS_IMPORT_ERROR: str | None = None
try:
    from neutts import NeuTTS  # noqa: F401

    _NEUTTS_AVAILABLE = True
except ImportError as e:
    _NEUTTS_IMPORT_ERROR = (
        "neutts not installed. Install with: pip install neutts "
        "or pip install \"neutts @ git+https://github.com/neuphonic/neutts.git\". "
        f"({e})"
    )

logger = logging.getLogger(__name__)

# Directory containing bundled reference voices (jo, dave, etc.)
_SAMPLES_DIR = (
    Path(__file__).resolve().parents[5] / "samples"
)

# Available bundled voices and their files
_BUNDLED_VOICES: dict[str, dict[str, str]] = {
    "jo": {"wav": "jo.wav", "txt": "jo.txt"},
    "dave": {"wav": "dave.wav", "txt": "dave.txt"},
}

# Class-level sticky flag: once codec falls back to CPU due to
# OOM, all future NeuTTSEngine instances reuse CPU automatically.
_codec_gpu_failed: bool = False


class NeuTTSEngine(TTSEngine):
    """Text-to-Speech using NeuTTS.

    NeuTTS is a voice-cloning model that synthesizes speech in the
    style of a reference audio sample.  When no custom reference is
    provided, a bundled default voice is used automatically.
    """

    name: ClassVar[str] = "NeuTTS"
    description: ClassVar[str] = "On-device NeuTTS voice-cloning TTS"
    SAMPLE_RATE: ClassVar[int] = 24000

    @classmethod
    def is_healthy(cls) -> bool:
        return _NEUTTS_AVAILABLE

    @classmethod
    def health_check_error(cls) -> str | None:
        return _NEUTTS_IMPORT_ERROR

    @classmethod
    def get_settings_schema(cls) -> List:
        from strawberry.shared.settings import FieldType, SettingField

        return [
            SettingField(
                key="backbone_repo",
                label="Backbone Repo",
                type=FieldType.TEXT,
                default="neuphonic/neutts-nano-q4-gguf",
                description="NeuTTS backbone repo or local path",
            ),
            SettingField(
                key="codec_repo",
                label="Codec Repo",
                type=FieldType.TEXT,
                default="neuphonic/distill-neucodec",
                description=(
                    "NeuCodec repo or local path. "
                    "Use neucodec-onnx-decoder for "
                    "decode-only (no voice cloning)"
                ),
            ),
            SettingField(
                key="language",
                label="Language",
                type=FieldType.TEXT,
                default="",
                description=(
                    "Optional eSpeak language code "
                    "(e.g. en-us, de, fr-fr). "
                    "Leave blank to auto-select."
                ),
            ),
            SettingField(
                key="voice",
                label="Voice",
                type=FieldType.SELECT,
                options=list(_BUNDLED_VOICES.keys()),
                default="jo",
                description=(
                    "Bundled reference voice used when "
                    "no custom ref_audio_path is set."
                ),
            ),
            SettingField(
                key="backbone_device",
                label="Backbone Device",
                type=FieldType.SELECT,
                options=["auto", "cpu", "cuda", "mps"],
                default="auto",
                description=(
                    "Device for NeuTTS backbone. "
                    "'auto' prefers CUDA > MPS > CPU."
                ),
            ),
            SettingField(
                key="codec_device",
                label="Codec Device",
                type=FieldType.SELECT,
                options=["auto", "cpu", "cuda", "mps"],
                default="auto",
                description=(
                    "Device for NeuCodec. "
                    "'auto' prefers CUDA > MPS > CPU. "
                    "Falls back to CPU on OOM."
                ),
            ),
            SettingField(
                key="ref_audio_path",
                label="Reference Audio Path",
                type=FieldType.TEXT,
                default="",
                description=(
                    "Optional path to a custom WAV for "
                    "voice cloning. Falls back to the "
                    "bundled voice if blank or missing."
                ),
            ),
            SettingField(
                key="ref_text",
                label="Reference Text",
                type=FieldType.TEXT,
                default="",
                description=(
                    "Transcript matching custom ref audio"
                ),
            ),
            SettingField(
                key="ref_text_path",
                label="Reference Text File",
                type=FieldType.TEXT,
                default="",
                description=(
                    "Path to transcript file "
                    "(used if Reference Text is blank)"
                ),
            ),
        ]

    def __init__(
        self,
        backbone_repo: str = "neuphonic/neutts-nano-q4-gguf",
        codec_repo: str = "neuphonic/distill-neucodec",
        language: str = "",
        voice: str = "jo",
        backbone_device: str = "auto",
        codec_device: str = "auto",
        ref_audio_path: str | None = None,
        ref_text: str | None = None,
        ref_text_path: str | None = None,
    ) -> None:
        try:
            from neutts import NeuTTS
        except ImportError as e:
            raise ImportError(
                "neutts not installed. Install with: "
                "pip install neutts or pip install "
                '"neutts @ git+https://github.com/'
                'neuphonic/neutts.git"'
            ) from e

        resolved_backbone = self._resolve_device(
            backbone_device, "backbone"
        )
        resolved_codec = self._resolve_codec_device(
            codec_repo, codec_device
        )

        # Try GPU first; on OOM, retry with CPU (sticky)
        self._model = self._init_model_with_fallback(
            NeuTTS,
            backbone_repo=backbone_repo,
            backbone_device=resolved_backbone,
            codec_repo=codec_repo,
            codec_device=resolved_codec,
            language=(language or "").strip() or None,
        )

        # Resolve reference audio: custom path > bundled voice
        self._resolve_references(
            voice, ref_audio_path, ref_text, ref_text_path
        )
        self._ref_codes = None

    # -----------------------------------------------------------------
    # Init helpers
    # -----------------------------------------------------------------

    @classmethod
    def _resolve_codec_device(
        cls, codec_repo: str, codec_device: str
    ) -> str:
        """Resolve codec device with ONNX and sticky-fallback rules.

        - ONNX codecs always run on CPU.
        - If a previous init OOM'd on GPU, stick with CPU.
        - Otherwise resolve normally.
        """
        global _codec_gpu_failed  # noqa: PLW0602
        if "onnx" in codec_repo.lower():
            return "cpu"
        if _codec_gpu_failed:
            logger.info(
                "NeuTTS codec: using CPU (sticky fallback "
                "from previous OOM)"
            )
            return "cpu"
        return cls._resolve_device(codec_device, "codec")

    @staticmethod
    def _init_model_with_fallback(
        model_cls, **kwargs
    ):
        """Instantiate NeuTTS, retrying on CPU if CUDA OOM.

        If the codec was on a GPU device and we get a CUDA OOM
        error, we set the sticky flag and retry with CPU.
        """
        global _codec_gpu_failed
        try:
            return model_cls(**kwargs)
        except Exception as e:
            err = str(e).lower()
            is_oom = "cuda" in err and (
                "out of memory" in err
                or "alloc" in err
            )
            codec_was_gpu = kwargs.get(
                "codec_device", "cpu"
            ) not in ("cpu",)

            if is_oom and codec_was_gpu:
                _codec_gpu_failed = True
                logger.warning(
                    "NeuTTS CUDA OOM on codec — "
                    "retrying with codec on CPU "
                    "(sticky fallback enabled)"
                )
                kwargs["codec_device"] = "cpu"
                return model_cls(**kwargs)
            raise

    def _resolve_references(
        self,
        voice: str,
        ref_audio_path: str | None,
        ref_text: str | None,
        ref_text_path: str | None,
    ) -> None:
        """Resolve reference audio and text.

        Priority:
        1. Custom ref_audio_path if set AND file exists
        2. Bundled voice from the `voice` setting

        Same logic for ref_text / ref_text_path.
        """
        custom_audio = (ref_audio_path or "").strip()
        custom_text = (ref_text or "").strip()
        custom_text_path = (ref_text_path or "").strip()

        # Try custom audio path
        if custom_audio and Path(custom_audio).exists():
            self._ref_audio_path = custom_audio
        elif custom_audio:
            logger.warning(
                "NeuTTS ref_audio_path '%s' not found; "
                "falling back to bundled voice '%s'",
                custom_audio,
                voice,
            )
            self._ref_audio_path = None
        else:
            self._ref_audio_path = None

        # Try custom text
        if custom_text:
            self._ref_text = custom_text
        elif custom_text_path and Path(custom_text_path).exists():
            self._ref_text = Path(
                custom_text_path
            ).read_text(encoding="utf-8").strip()
        else:
            self._ref_text = None

        # Fall back to bundled voice if no custom ref
        if not self._ref_audio_path:
            self._apply_bundled_voice(voice)

        self._ref_text_path = None  # Already resolved above

    def _apply_bundled_voice(self, voice: str) -> None:
        """Set ref audio and text from bundled samples."""
        voice = voice.lower().strip()
        if voice not in _BUNDLED_VOICES:
            logger.warning(
                "Unknown bundled voice '%s'; "
                "falling back to 'jo'",
                voice,
            )
            voice = "jo"

        files = _BUNDLED_VOICES[voice]
        wav_path = _SAMPLES_DIR / files["wav"]
        txt_path = _SAMPLES_DIR / files["txt"]

        if not wav_path.exists():
            raise FileNotFoundError(
                f"Bundled voice '{voice}' WAV not found "
                f"at {wav_path}. Ensure the samples "
                "directory is present."
            )

        self._ref_audio_path = str(wav_path)
        if not self._ref_text and txt_path.exists():
            self._ref_text = txt_path.read_text(
                encoding="utf-8"
            ).strip()

        logger.info(
            "NeuTTS using bundled voice '%s' from %s",
            voice,
            wav_path,
        )

    # -----------------------------------------------------------------
    # Device resolution
    # -----------------------------------------------------------------

    @staticmethod
    def _resolve_device(
        requested: str | None, component: str
    ) -> str:
        """Resolve device with safe fallback.

        `auto` prefers CUDA, then MPS, then CPU.
        Explicit CUDA/MPS requests fall back to CPU
        if unavailable.
        """
        normalized = (requested or "auto").strip().lower()

        try:
            import torch
        except Exception:
            if normalized in {"auto", "cpu"}:
                return "cpu"
            logger.warning(
                "NeuTTS %s device '%s' requested but "
                "torch is unavailable; falling back to CPU",
                component,
                normalized,
            )
            return "cpu"

        has_cuda = bool(torch.cuda.is_available())
        has_mps = bool(
            hasattr(torch.backends, "mps")
            and torch.backends.mps.is_available()
        )

        if normalized == "auto":
            if has_cuda:
                return "cuda"
            if has_mps:
                return "mps"
            return "cpu"

        if normalized == "cuda" and not has_cuda:
            logger.warning(
                "NeuTTS %s device 'cuda' requested but "
                "CUDA is unavailable; falling back to CPU",
                component,
            )
            return "cpu"

        if normalized == "mps" and not has_mps:
            logger.warning(
                "NeuTTS %s device 'mps' requested but "
                "MPS is unavailable; falling back to CPU",
                component,
            )
            return "cpu"

        if normalized not in {"cpu", "cuda", "mps"}:
            logger.warning(
                "NeuTTS %s device '%s' is invalid; "
                "falling back to CPU",
                component,
                normalized,
            )
            return "cpu"

        return normalized

    # -----------------------------------------------------------------
    # Reference handling
    # -----------------------------------------------------------------

    @property
    def sample_rate(self) -> int:
        return self.SAMPLE_RATE

    def _ensure_reference(self) -> tuple[object, str]:
        """Return (ref_codes, ref_text), encoding on first call."""
        if not self._ref_audio_path:
            raise ValueError(
                "NeuTTS has no reference audio. "
                "Set ref_audio_path or ensure bundled "
                "samples are present."
            )

        if not self._ref_text:
            raise ValueError(
                "NeuTTS has no reference transcript. "
                "Set ref_text or ref_text_path."
            )

        if self._ref_codes is None:
            logger.info(
                "Encoding reference audio: %s",
                self._ref_audio_path,
            )
            self._ref_codes = self._model.encode_reference(
                self._ref_audio_path
            )

        return self._ref_codes, self._ref_text

    # -----------------------------------------------------------------
    # Synthesis
    # -----------------------------------------------------------------

    def synthesize(self, text: str) -> AudioChunk:
        if not text or not text.strip():
            return AudioChunk(
                audio=np.array([], dtype=np.int16),
                sample_rate=self.sample_rate,
            )

        ref_codes, ref_text = self._ensure_reference()
        wav = self._model.infer(text, ref_codes, ref_text)
        audio = self._to_int16(wav)
        return AudioChunk(audio=audio, sample_rate=self.sample_rate)

    def synthesize_stream(self, text: str) -> Iterator[AudioChunk]:
        """Synthesize text with streaming output."""
        if not text or not text.strip():
            yield AudioChunk(
                audio=np.array([], dtype=np.int16),
                sample_rate=self.sample_rate,
            )
            return

        # NeuTTS streaming requires GGUF backbone.
        # Fall back to block synthesis for PyTorch.
        if not getattr(
            self._model, "_is_quantized_model", False
        ):
            yield self.synthesize(text)
            return

        ref_codes, ref_text = self._ensure_reference()
        for chunk_wav in self._model.infer_stream(
            text, ref_codes, ref_text
        ):
            audio = self._to_int16(chunk_wav)
            yield AudioChunk(
                audio=audio, sample_rate=self.sample_rate
            )

    # -----------------------------------------------------------------
    # Utilities
    # -----------------------------------------------------------------

    def _to_int16(self, audio: object) -> np.ndarray:
        arr = np.asarray(audio)
        arr = np.squeeze(arr)

        if arr.dtype in (np.float32, np.float64):
            arr = np.clip(arr, -1.0, 1.0)
            arr = (arr * 32767).astype(np.int16)
        elif arr.dtype != np.int16:
            arr = arr.astype(np.int16)

        return arr

    def cleanup(self) -> None:
        """Manually clear resources and release CUDA cache."""
        if hasattr(self, "_model"):
            del self._model
            self._model = None

        if hasattr(self, "_ref_codes"):
            del self._ref_codes
            self._ref_codes = None

        import gc
        gc.collect()

        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            if (
                hasattr(torch.backends, "mps")
                and torch.backends.mps.is_available()
            ):
                torch.mps.empty_cache()
        except ImportError:
            pass
