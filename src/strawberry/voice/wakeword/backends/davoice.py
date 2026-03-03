"""DaVoice wake word backend.

Uses Python_WakeWordDetection / keyword_detection_lib in external-audio mode.
Docs: https://github.com/frymanofer/Python_WakeWordDetection
"""

from __future__ import annotations

import os
from collections import deque
from pathlib import Path
from threading import Lock
from typing import ClassVar, Deque, List

import numpy as np

from ..base import WakeWordDetector

_DAVOICE_AVAILABLE = False
_DAVOICE_IMPORT_ERROR: str | None = None
try:
    from keyword_detection import KeywordDetection  # noqa: F401

    _DAVOICE_AVAILABLE = True
except ImportError as e:
    _DAVOICE_IMPORT_ERROR = (
        "keyword_detection not available. Install keyword-detection-lib and ensure "
        f"its runtime deps are installed (notably pyaudio/portaudio). ({e})"
    )


class DaVoiceDetector(WakeWordDetector):
    """Wake word detection using DaVoice keyword_detection_lib.

    This backend uses external-audio mode and consumes audio frames from VoiceCore.
    DaVoice models are ONNX files, typically custom-trained wake phrases.
    """

    name: ClassVar[str] = "DaVoice"
    description: ClassVar[str] = (
        "Wake word detection via DaVoice keyword_detection_lib and ONNX wake models."
    )

    DEFAULT_SAMPLE_RATE: ClassVar[int] = 16000
    DEFAULT_FRAME_LENGTH: ClassVar[int] = 1280

    @classmethod
    def is_healthy(cls) -> bool:
        return _DAVOICE_AVAILABLE

    @classmethod
    def health_check_error(cls) -> str | None:
        return _DAVOICE_IMPORT_ERROR

    @classmethod
    def get_settings_schema(cls) -> List:
        from strawberry.shared.settings import FieldType, SettingField

        return [
            SettingField(
                key="license_key",
                label="DaVoice License Key",
                type=FieldType.PASSWORD,
                secret=True,
                env_key="DAVOICE_LICENSE_KEY",
                description="License key from DaVoice",
                metadata={
                    "api_key_url": "https://davoice.io/",
                },
            ),
            SettingField(
                key="model_paths",
                label="Model Paths",
                type=FieldType.TEXT,
                default="",
                description=(
                    "Comma-separated ONNX model paths. If empty, wake keywords are "
                    "interpreted as model paths."
                ),
            ),
            SettingField(
                key="threshold",
                label="Threshold",
                type=FieldType.NUMBER,
                default=0.9,
                min_value=0.0,
                max_value=1.0,
                description="Detection threshold",
            ),
            SettingField(
                key="buffer_cnt",
                label="Buffer Count",
                type=FieldType.NUMBER,
                default=4,
                min_value=1,
                max_value=16,
                description=(
                    "Sub-model count per buffer "
                    "(higher can reduce false positives)"
                ),
            ),
            SettingField(
                key="wait_time",
                label="Wait Time (ms)",
                type=FieldType.NUMBER,
                default=50,
                min_value=0,
                max_value=1000,
                description="Delay between inferences",
            ),
            SettingField(
                key="buffer_ms",
                label="Buffer (ms)",
                type=FieldType.NUMBER,
                default=100,
                min_value=20,
                max_value=1000,
                description="Internal DaVoice audio buffer size",
            ),
            SettingField(
                key="frame_length",
                label="Frame Length",
                type=FieldType.NUMBER,
                default=1280,
                min_value=160,
                max_value=8192,
                description="Input frame size in samples (16kHz PCM16 mono)",
            ),
            SettingField(
                key="enable_vad",
                label="Enable DaVoice VAD",
                type=FieldType.CHECKBOX,
                default=False,
                description="Enable DaVoice's internal VAD while detecting wake words",
            ),
        ]

    def __init__(
        self,
        keywords: List[str],
        sensitivity: float = 0.5,
        license_key: str | None = None,
        model_paths: str | None = None,
        threshold: float = 0.9,
        buffer_cnt: int = 4,
        wait_time: int = 50,
        buffer_ms: int = 100,
        frame_length: int = DEFAULT_FRAME_LENGTH,
        enable_vad: bool = False,
    ):
        if not _DAVOICE_AVAILABLE:
            raise ImportError(_DAVOICE_IMPORT_ERROR or "DaVoice backend unavailable")

        from keyword_detection import KeywordDetection

        self._sensitivity = sensitivity
        self._sample_rate = self.DEFAULT_SAMPLE_RATE
        self._frame_length = int(frame_length)

        self._detected_indices: Deque[int] = deque()
        self._detect_lock = Lock()

        self._keywords = list(keywords)
        self._model_paths = self._resolve_model_paths(keywords, model_paths)

        self._keyword_detection = KeywordDetection(
            keyword_models=self._build_models(
                threshold=threshold,
                buffer_cnt=buffer_cnt,
                wait_time=wait_time,
            )
        )

        resolved_license = license_key or os.environ.get("DAVOICE_LICENSE_KEY")
        if not resolved_license:
            raise ValueError(
                "DaVoice license key required. "
                "Set DAVOICE_LICENSE_KEY or voice.wakeword.davoice.license_key."
            )

        self._keyword_detection.set_keyword_detection_license(resolved_license)
        self._keyword_detection.start_keyword_detection_external_audio(
            enable_vad=bool(enable_vad),
            buffer_ms=int(buffer_ms),
        )

    def _resolve_model_paths(
        self,
        keywords: List[str],
        model_paths: str | None,
    ) -> List[str]:
        if model_paths and model_paths.strip():
            paths = [p.strip() for p in model_paths.split(",") if p.strip()]
        else:
            paths = list(keywords)

        if not paths:
            raise ValueError(
                "DaVoice requires at least one ONNX model path via "
                "model_paths or keywords"
            )

        resolved = []
        for path in paths:
            if not path.lower().endswith(".onnx"):
                raise ValueError(
                    f"DaVoice model path must be an .onnx file: '{path}'"
                )
            if not Path(path).exists():
                raise ValueError(f"DaVoice model path does not exist: {path}")
            resolved.append(path)

        return resolved

    def _build_models(
        self,
        threshold: float,
        buffer_cnt: int,
        wait_time: int,
    ) -> List[dict]:
        models: List[dict] = []
        for idx, model_path in enumerate(self._model_paths):
            models.append(
                {
                    "model_path": model_path,
                    "callback_function": self._make_callback(idx),
                    "threshold": float(threshold),
                    "buffer_cnt": int(buffer_cnt),
                    "wait_time": int(wait_time),
                }
            )
        return models

    def _make_callback(self, index: int):
        def _callback(params):
            with self._detect_lock:
                self._detected_indices.append(index)

        return _callback

    @property
    def keywords(self) -> List[str]:
        if self._keywords:
            return self._keywords
        return [Path(path).stem for path in self._model_paths]

    @property
    def frame_length(self) -> int:
        return self._frame_length

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def process(self, audio_frame: np.ndarray) -> int:
        frame = np.asarray(audio_frame, dtype=np.int16)

        if frame.ndim > 1:
            frame = frame.reshape(-1)

        if len(frame) != self._frame_length:
            if len(frame) < self._frame_length:
                padded = np.zeros(self._frame_length, dtype=np.int16)
                padded[: len(frame)] = frame
                frame = padded
            else:
                frame = frame[: self._frame_length]

        self._keyword_detection.feed_audio_frame(frame)

        with self._detect_lock:
            if self._detected_indices:
                return self._detected_indices.popleft()

        return -1

    def cleanup(self) -> None:
        # Library doesn't expose a single stable stop API across versions.
        for method_name in (
            "stop_keyword_detection",
            "stop",
            "close",
            "shutdown",
        ):
            method = getattr(self._keyword_detection, method_name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    pass
