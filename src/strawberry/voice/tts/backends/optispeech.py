"""OptiSpeech backend.

Requires: pip install optispeech
Project: https://github.com/mush42/optispeech
"""

from __future__ import annotations

from typing import Any, ClassVar, List

import numpy as np

from ..base import AudioChunk, TTSEngine

_OPTISPEECH_AVAILABLE = False
_OPTISPEECH_IMPORT_ERROR: str | None = None
try:
    from optispeech.model import OptiSpeech  # noqa: F401

    _OPTISPEECH_AVAILABLE = True
except ImportError as e:
    _OPTISPEECH_IMPORT_ERROR = (
        "optispeech not installed. Install with: pip install optispeech. "
        f"({e})"
    )


class OptiSpeechTTS(TTSEngine):
    """Text-to-Speech using OptiSpeech checkpoints."""

    name: ClassVar[str] = "OptiSpeech"
    description: ClassVar[str] = "Open-source TTS via OptiSpeech checkpoint"

    @classmethod
    def is_healthy(cls) -> bool:
        return _OPTISPEECH_AVAILABLE

    @classmethod
    def health_check_error(cls) -> str | None:
        return _OPTISPEECH_IMPORT_ERROR

    @classmethod
    def get_settings_schema(cls) -> List:
        from strawberry.shared.settings import FieldType, SettingField

        return [
            SettingField(
                key="checkpoint_path",
                label="Checkpoint Path",
                type=FieldType.TEXT,
                default="",
                description="Path to OptiSpeech .ckpt file",
            ),
            SettingField(
                key="device",
                label="Device",
                type=FieldType.SELECT,
                options=["auto", "cpu", "cuda", "mps"],
                default="auto",
                description="Inference device",
            ),
            SettingField(
                key="d_factor",
                label="Duration Factor",
                type=FieldType.NUMBER,
                default=1.0,
                min_value=0.5,
                max_value=2.0,
                description="Speech rate control (lower=faster, higher=slower)",
            ),
            SettingField(
                key="p_factor",
                label="Pitch Factor",
                type=FieldType.NUMBER,
                default=1.0,
                min_value=0.5,
                max_value=2.0,
                description="Pitch scaling factor",
            ),
            SettingField(
                key="e_factor",
                label="Energy Factor",
                type=FieldType.NUMBER,
                default=1.0,
                min_value=0.5,
                max_value=2.0,
                description="Loudness/energy scaling factor",
            ),
        ]

    def __init__(
        self,
        checkpoint_path: str = "",
        device: str = "auto",
        d_factor: float = 1.0,
        p_factor: float = 1.0,
        e_factor: float = 1.0,
    ) -> None:
        self._checkpoint_path = checkpoint_path.strip()
        self._device = device
        self._d_factor = d_factor
        self._p_factor = p_factor
        self._e_factor = e_factor
        self._model = None
        self._sample_rate_val = 22050

    @property
    def sample_rate(self) -> int:
        return self._sample_rate_val

    def _resolve_torch_device(self) -> str:
        if self._device != "auto":
            return self._device

        try:
            import torch

            if torch.cuda.is_available():
                return "cuda"
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
        except Exception:
            pass
        return "cpu"

    def _ensure_model(self) -> None:
        if self._model is not None:
            return

        if not self._checkpoint_path:
            raise ValueError(
                "OptiSpeech requires checkpoint_path. "
                "Configure voice.tts.optispeech.checkpoint_path."
            )

        try:
            import torch
            from optispeech.model import OptiSpeech
        except ImportError as e:
            raise ImportError(
                "optispeech not installed. Install with: pip install optispeech"
            ) from e

        device = self._resolve_torch_device()
        map_location: Any = torch.device(device) if device != "auto" else "cpu"

        model = OptiSpeech.load_from_checkpoint(
            self._checkpoint_path,
            map_location=map_location,
        )
        model.eval()
        model = model.to(torch.device(device))

        sample_rate = getattr(model, "sample_rate", None)
        if isinstance(sample_rate, int) and sample_rate > 0:
            self._sample_rate_val = sample_rate

        self._model = model

    def synthesize(self, text: str) -> AudioChunk:
        if not text or not text.strip():
            return AudioChunk(
                audio=np.array([], dtype=np.int16),
                sample_rate=self.sample_rate,
            )

        self._ensure_model()
        assert self._model is not None

        inputs = self._model.prepare_input(text)

        try:
            outputs = self._model.synthesize(
                inputs,
                d_factor=self._d_factor,
                p_factor=self._p_factor,
                e_factor=self._e_factor,
            )
        except TypeError:
            outputs = self._model.synthesize(inputs)

        audio = self._extract_audio(outputs)
        return AudioChunk(audio=audio, sample_rate=self.sample_rate)

    def _extract_audio(self, outputs: object) -> np.ndarray:
        np_outputs = outputs.as_numpy() if hasattr(outputs, "as_numpy") else outputs

        if isinstance(np_outputs, dict):
            audio = np_outputs.get("wav")
            if audio is None:
                audio = np_outputs.get("audio")
            if audio is None:
                raise RuntimeError("OptiSpeech output missing wav/audio fields")
            return self._to_int16(audio)

        if hasattr(np_outputs, "wav"):
            return self._to_int16(np_outputs.wav)

        return self._to_int16(np_outputs)

    def _to_int16(self, audio: object) -> np.ndarray:
        arr = np.asarray(audio)
        arr = np.squeeze(arr)

        if arr.dtype in (np.float32, np.float64):
            arr = np.clip(arr, -1.0, 1.0)
            arr = (arr * 32767).astype(np.int16)
        elif arr.dtype != np.int16:
            arr = arr.astype(np.int16)

        return arr
