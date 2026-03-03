"""Qwen3-TTS backend.

Requires: pip install qwen-tts
Project: https://github.com/QwenLM/Qwen3-TTS
"""

from __future__ import annotations

import importlib.util
from typing import ClassVar, List

import numpy as np

from ..base import AudioChunk, TTSEngine

_QWEN3_TTS_AVAILABLE = False
_QWEN3_TTS_IMPORT_ERROR: str | None = None
if importlib.util.find_spec("qwen_tts"):
    _QWEN3_TTS_AVAILABLE = True
else:
    _QWEN3_TTS_IMPORT_ERROR = "qwen-tts not installed. Install with: pip install qwen-tts"


class Qwen3TTSEngine(TTSEngine):
    """Text-to-Speech using Qwen3-TTSModel."""

    name: ClassVar[str] = "Qwen3 TTS"
    description: ClassVar[str] = "Open-source Qwen3 TTS with custom voice support"
    DEFAULT_MODEL: ClassVar[str] = "Qwen/Qwen3-TTS-0.6B-CustomVoice"
    DEFAULT_SAMPLE_RATE: ClassVar[int] = 24000

    @classmethod
    def is_healthy(cls) -> bool:
        return _QWEN3_TTS_AVAILABLE

    @classmethod
    def health_check_error(cls) -> str | None:
        return _QWEN3_TTS_IMPORT_ERROR

    @classmethod
    def get_settings_schema(cls) -> List:
        from strawberry.shared.settings import FieldType, SettingField

        return [
            SettingField(
                key="model",
                label="Model",
                type=FieldType.TEXT,
                default=cls.DEFAULT_MODEL,
                description="Qwen3-TTS HuggingFace model id",
            ),
            SettingField(
                key="language",
                label="Language",
                type=FieldType.TEXT,
                default="English",
                description="Language string for custom voice mode",
            ),
            SettingField(
                key="speaker",
                label="Speaker",
                type=FieldType.TEXT,
                default="Ryan",
                description="Speaker name for custom voice mode",
            ),
            SettingField(
                key="instruct",
                label="Instruct",
                type=FieldType.TEXT,
                default="",
                description="Optional speaking style instruction",
            ),
            SettingField(
                key="device_map",
                label="Device Map",
                type=FieldType.TEXT,
                default="auto",
                description="HF device_map value (auto, cpu, cuda, etc)",
            ),
            SettingField(
                key="dtype",
                label="DType",
                type=FieldType.SELECT,
                options=["auto", "float16", "bfloat16", "float32"],
                default="auto",
                description="Model dtype",
            ),
            SettingField(
                key="attn_implementation",
                label="Attention Impl",
                type=FieldType.SELECT,
                options=["sdpa", "flash_attention_2"],
                default="flash_attention_2",
                description="Attention implementation",
            ),
        ]

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        language: str = "English",
        speaker: str = "Ryan",
        instruct: str | None = None,
        device_map: str = "auto",
        dtype: str = "auto",
        attn_implementation: str = "flash_attention_2",
    ) -> None:
        self._model_name = model or self.DEFAULT_MODEL
        self._language = language or "English"
        self._speaker = speaker or "Ryan"
        self._instruct = (instruct or "").strip() or None
        self._device_map = device_map or "auto"
        self._dtype_name = dtype or "auto"
        self._attn_implementation = attn_implementation or "flash_attention_2"

        self._model = None
        self._sample_rate_val = self.DEFAULT_SAMPLE_RATE

    @property
    def sample_rate(self) -> int:
        return self._sample_rate_val

    def _resolve_dtype(self):
        if self._dtype_name == "auto":
            return "auto"

        import torch

        mapping = {
            "float16": torch.float16,
            "bfloat16": torch.bfloat16,
            "float32": torch.float32,
        }
        return mapping.get(self._dtype_name, "auto")

    def _ensure_model(self) -> None:
        if self._model is not None:
            return

        try:
            from qwen_tts import Qwen3TTSModel
        except ImportError as e:
            raise ImportError(
                "qwen-tts not installed. Install with: pip install qwen-tts"
            ) from e

        self._model = Qwen3TTSModel.from_pretrained(
            self._model_name,
            device_map=self._device_map,
            dtype=self._resolve_dtype(),
            attn_implementation=self._attn_implementation,
        )

    def synthesize(self, text: str) -> AudioChunk:
        if not text or not text.strip():
            return AudioChunk(
                audio=np.array([], dtype=np.int16),
                sample_rate=self.sample_rate,
            )

        self._ensure_model()
        assert self._model is not None

        kwargs = {
            "text": text,
            "language": self._language,
            "speaker": self._speaker,
        }
        if self._instruct:
            kwargs["instruct"] = self._instruct

        wavs, sr = self._model.generate_custom_voice(**kwargs)
        if not wavs:
            return AudioChunk(
                audio=np.array([], dtype=np.int16),
                sample_rate=self.sample_rate,
            )

        self._sample_rate_val = int(sr)
        audio = self._to_int16(wavs[0])
        return AudioChunk(audio=audio, sample_rate=self._sample_rate_val)

    def _to_int16(self, audio: object) -> np.ndarray:
        arr = np.asarray(audio)
        arr = np.squeeze(arr)

        if arr.dtype in (np.float32, np.float64):
            arr = np.clip(arr, -1.0, 1.0)
            arr = (arr * 32767).astype(np.int16)
        elif arr.dtype != np.int16:
            arr = arr.astype(np.int16)

        return arr
