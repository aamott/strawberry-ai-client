"""Faster-Whisper STT with Live GPU Monitoring."""

from __future__ import annotations

from typing import Optional

import pynvml
import torch
from faster_whisper import WhisperModel

try:
    from ..base import STTEngine, TranscriptionResult
except ImportError:
    from base import STTEngine, TranscriptionResult

class FasterWhisperSTT(STTEngine):
    """
    Medium.en Whisper model with optional real-time GPU stats.
    """

    def __init__(
        self,
        model_size: str = "medium.en",
        device: Optional[str] = None,
        precision: str = "float16",
        monitor_gpu: bool = True, # Toggle to enable/disable live stats
        **kwargs
    ) -> None:
        self._sample_rate = 16000
        self._monitor_gpu = monitor_gpu
        self._device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        # Initialize NVML for monitoring if enabled
        if self._monitor_gpu and "cuda" in self._device:
            try:
                pynvml.nvmlInit()
                self._gpu_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            except Exception as e:
                print(f"Warning: Could not init GPU monitor: {e}")
                self._monitor_gpu = False

        # VRAM Safety Check for 4GB Cards
        compute_type = precision
        if "cuda" in self._device:
            total_vram = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            if total_vram <= 4.1:
                compute_type = "int8_float16"

        self._model = WhisperModel(
            model_size,
            device=self._device,
            compute_type=compute_type
        )

    def _log_stats(self, stage: str):
        """Helper to print current GPU health."""
        if not self._monitor_gpu:
            return

        info = pynvml.nvmlDeviceGetMemoryInfo(self._gpu_handle)
        temp = pynvml.nvmlDeviceGetTemperature(self._gpu_handle, pynvml.NVML_TEMPERATURE_GPU)
        used_gb = info.used / (1024**3)
        total_gb = info.total / (1024**3)

        print(f"[{stage}] VRAM: {used_gb:.2f}/{total_gb:.2f} GB | Temp: {temp}°C")

    def transcribe(self, audio_path: str, *, timestamps: bool = False) -> TranscriptionResult:
        self._log_stats("Pre-Inference")

        segments, _ = self._model.transcribe(
            audio_path,
            beam_size=5,
            word_timestamps=timestamps,
            vad_filter=True
        )

        segments = list(segments)
        full_text = " ".join([s.text.strip() for s in segments]).strip()

        self._log_stats("Post-Inference")

        timestamp_data = None
        if timestamps:
            timestamp_data = [{"start": s.start, "end": s.end, "text": s.text} for s in segments]

        return TranscriptionResult(text=full_text, timestamps=timestamp_data)

    def cleanup(self) -> None:
        if self._monitor_gpu:
            pynvml.nvmlShutdown()
        del self._model
        torch.cuda.empty_cache()
