"""NeuTTS backend.

Requires: pip install neutts
Project: https://github.com/neuphonic/neutts
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar, List

import numpy as np

from ..base import AudioChunk, TTSEngine

_NEUTTS_AVAILABLE = False
_NEUTTS_IMPORT_ERROR: str | None = None
try:
    from neutts import NeuTTS  # noqa: F401

    _NEUTTS_AVAILABLE = True
except ImportError as e:
    _NEUTTS_IMPORT_ERROR = (
        "neutts not installed. Install with: pip install neutts. " f"({e})"
    )

logger = logging.getLogger(__name__)


class NeuTTSEngine(TTSEngine):
    """Text-to-Speech using NeuTTS.

    NeuTTS is primarily a voice-cloning model. Typical synthesis requires:
    - reference audio (for voice style)
    - matching reference text transcript
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
                default="neuphonic/neutts-nano",
                description="NeuTTS backbone repo or local path",
            ),
            SettingField(
                key="codec_repo",
                label="Codec Repo",
                type=FieldType.TEXT,
                default="neuphonic/neucodec",
                description="NeuCodec repo or local path",
            ),
            SettingField(
                key="language",
                label="Language",
                type=FieldType.TEXT,
                default="",
                description=(
                    "Optional eSpeak language code (e.g. en-us, de, fr-fr). "
                    "Leave blank to auto-select for known Neuphonic backbones."
                ),
            ),
            SettingField(
                key="backbone_device",
                label="Backbone Device",
                type=FieldType.SELECT,
                options=["auto", "cpu", "cuda", "mps"],
                default="auto",
                description=(
                    "Device for NeuTTS backbone inference. "
                    "'auto' prefers CUDA, then MPS, then CPU."
                ),
            ),
            SettingField(
                key="codec_device",
                label="Codec Device",
                type=FieldType.SELECT,
                options=["auto", "cpu", "cuda", "mps"],
                default="auto",
                description=(
                    "Device for NeuCodec inference. "
                    "'auto' prefers CUDA, then MPS, then CPU."
                ),
            ),
            SettingField(
                key="ref_audio_path",
                label="Reference Audio Path",
                type=FieldType.TEXT,
                default="",
                description="Path to reference WAV used for voice cloning",
            ),
            SettingField(
                key="ref_text",
                label="Reference Text",
                type=FieldType.TEXT,
                default="",
                description="Transcript matching the reference audio",
            ),
            SettingField(
                key="ref_text_path",
                label="Reference Text File",
                type=FieldType.TEXT,
                default="",
                description="Path to transcript file (used if Reference Text is blank)",
            ),
        ]

    def __init__(
        self,
        backbone_repo: str = "neuphonic/neutts-nano",
        codec_repo: str = "neuphonic/neucodec",
        language: str = "",
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
                "neutts not installed. Install with: pip install neutts"
            ) from e

        resolved_backbone_device = self._resolve_device(backbone_device, "backbone")
        resolved_codec_device = self._resolve_device(codec_device, "codec")

        self._model = NeuTTS(
            backbone_repo=backbone_repo,
            backbone_device=resolved_backbone_device,
            codec_repo=codec_repo,
            codec_device=resolved_codec_device,
            language=(language or "").strip() or None,
        )

        self._ref_audio_path = (ref_audio_path or "").strip() or None
        self._ref_text = (ref_text or "").strip() or None
        self._ref_text_path = (ref_text_path or "").strip() or None
        self._ref_codes = None

    @staticmethod
    def _resolve_device(requested: str | None, component: str) -> str:
        """Resolve device with safe fallback.

        `auto` prefers CUDA, then MPS, then CPU.
        Explicit CUDA/MPS requests fall back to CPU if unavailable.
        """
        normalized = (requested or "auto").strip().lower()

        try:
            import torch
        except Exception:
            if normalized in {"auto", "cpu"}:
                return "cpu"
            logger.warning(
                "NeuTTS %s device '%s' requested but torch is unavailable; "
                "falling back to CPU",
                component,
                normalized,
            )
            return "cpu"

        has_cuda = bool(torch.cuda.is_available())
        has_mps = bool(
            hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
        )

        if normalized == "auto":
            if has_cuda:
                return "cuda"
            if has_mps:
                return "mps"
            return "cpu"

        if normalized == "cuda" and not has_cuda:
            logger.warning(
                "NeuTTS %s device 'cuda' requested but CUDA is unavailable; "
                "falling back to CPU",
                component,
            )
            return "cpu"

        if normalized == "mps" and not has_mps:
            logger.warning(
                "NeuTTS %s device 'mps' requested but MPS is unavailable; "
                "falling back to CPU",
                component,
            )
            return "cpu"

        if normalized not in {"cpu", "cuda", "mps"}:
            logger.warning(
                "NeuTTS %s device '%s' is invalid; falling back to CPU",
                component,
                normalized,
            )
            return "cpu"

        return normalized

    @property
    def sample_rate(self) -> int:
        return self.SAMPLE_RATE

    def _load_reference_text(self) -> str | None:
        if self._ref_text:
            return self._ref_text
        if not self._ref_text_path:
            return None

        path = Path(self._ref_text_path)
        if not path.exists():
            raise ValueError(f"NeuTTS ref_text_path does not exist: {path}")
        return path.read_text(encoding="utf-8").strip()

    def _ensure_reference(self) -> tuple[object, str]:
        if not self._ref_audio_path:
            raise ValueError(
                "NeuTTS requires ref_audio_path for voice cloning. "
                "Configure voice.tts.neutts.ref_audio_path."
            )

        ref_text = self._load_reference_text()
        if not ref_text:
            raise ValueError(
                "NeuTTS requires reference transcript text. "
                "Set ref_text or ref_text_path."
            )

        if self._ref_codes is None:
            self._ref_codes = self._model.encode_reference(self._ref_audio_path)

        return self._ref_codes, ref_text

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

    def _to_int16(self, audio: object) -> np.ndarray:
        arr = np.asarray(audio)
        arr = np.squeeze(arr)

        if arr.dtype in (np.float32, np.float64):
            arr = np.clip(arr, -1.0, 1.0)
            arr = (arr * 32767).astype(np.int16)
        elif arr.dtype != np.int16:
            arr = arr.astype(np.int16)

        return arr
