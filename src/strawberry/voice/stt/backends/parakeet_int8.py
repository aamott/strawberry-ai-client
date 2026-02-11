"""Sherpa-ONNX Parakeet TDT 0.6B INT8 backend.
Warning: this is pretty slow and requires a lot of resources.
"""

from __future__ import annotations

import inspect
import os
import wave
from typing import List, Optional

import numpy as np
import sherpa_onnx

try:
    from ..base import STTEngine, TranscriptionResult
except ImportError:
    from base import STTEngine, TranscriptionResult


class SherpaParakeetSTT(STTEngine):
    """Parakeet TDT 0.6B v2 via Sherpa-ONNX (INT8 quantized)."""

    name = "Sherpa-ONNX Parakeet TDT (INT8)"
    description = "Ultra-lightweight STT using ONNX Runtime. Fits in <1.5GB VRAM."

    def __init__(
        self,
        model_dir: str = "models/parakeet-tdt-0.6b-int8",
        device: Optional[str] = None,
        precision: str | None = None,
    ) -> None:
        """Initialize the Sherpa-ONNX Parakeet backend.

        Args:
            model_dir: Directory containing ONNX model artifacts.
            device: Execution device hint ("cpu", "cuda", or "cuda:0").
            precision: Unused; accepted for CLI compatibility.
        """
        self._sample_rate = 16000
        self._device = self._normalize_device(device)
        self._precision = precision

        # Favor factory helpers for broader sherpa-onnx compatibility.
        if hasattr(sherpa_onnx.OfflineRecognizer, "from_transducer"):
            self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=os.path.join(model_dir, "encoder.int8.onnx"),
                decoder=os.path.join(model_dir, "decoder.int8.onnx"),
                joiner=os.path.join(model_dir, "joiner.int8.onnx"),
                tokens=os.path.join(model_dir, "tokens.txt"),
                num_threads=2,
                sample_rate=self._sample_rate,
                feature_dim=80,
                debug=False,
            )
        else:
            self._recognizer = self._build_recognizer_with_configs(model_dir)

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def transcribe(
        self, audio_path: str, *, timestamps: bool = False
    ) -> TranscriptionResult:
        """Transcribe a single audio file.

        Args:
            audio_path: Path to a mono 16-bit WAV file.
            timestamps: Whether to include timestamps (if supported).

        Returns:
            TranscriptionResult containing text (and optional timestamps).
        """
        samples, sr = self._read_wave(audio_path)

        # Create a stream and recognize
        stream = self._recognizer.create_stream()
        stream.accept_waveform(sr, samples)
        self._recognizer.decode_stream(stream)

        result = stream.result
        return TranscriptionResult(
            text=result.text.strip(),
            # Sherpa-ONNX provides timestamps in result.timestamps if supported.
            timestamps=result.timestamps if timestamps else None,
        )

    def transcribe_batch(
        self,
        audio_paths: List[str],
        *,
        timestamps: bool = False,
    ) -> List[TranscriptionResult]:
        """Transcribe multiple audio files.

        Args:
            audio_paths: Paths to mono 16-bit WAV files.
            timestamps: Whether to include timestamps (if supported).

        Returns:
            A list of transcription results.
        """
        return [self.transcribe(path, timestamps=timestamps) for path in audio_paths]

    def _read_wave(self, filename: str) -> tuple[np.ndarray, int]:
        """Read a WAV file into the format Sherpa-ONNX expects.

        Args:
            filename: Path to a mono 16-bit WAV file.

        Returns:
            Tuple of float32 samples and sample rate.
        """
        with wave.open(filename, "rb") as f:
            assert f.getnchannels() == 1, "Only mono wave files are supported"
            assert f.getsampwidth() == 2, "Only 16-bit wave files are supported"
            num_samples = f.getnframes()
            samples = f.readframes(num_samples)
            samples_int16 = np.frombuffer(samples, dtype=np.int16)
            samples_float32 = samples_int16.astype(np.float32) / 32768
            return samples_float32, f.getframerate()

    def _normalize_device(self, device: Optional[str]) -> str:
        """Normalize device strings into ONNX Runtime-compatible values.

        Args:
            device: Raw device string from the CLI or caller.

        Returns:
            "cuda" or "cpu" depending on availability.
        """
        if device is None:
            return "cuda"
        normalized = device.lower()
        if normalized.startswith("cuda"):
            return "cuda"
        if normalized == "cpu":
            return "cpu"
        return "cpu"

    def _build_recognizer_with_configs(
        self,
        model_dir: str,
    ) -> sherpa_onnx.OfflineRecognizer:
        """Create an offline recognizer for older sherpa-onnx builds.

        Args:
            model_dir: Directory containing ONNX model artifacts.

        Returns:
            A configured OfflineRecognizer instance.
        """
        if not hasattr(sherpa_onnx, "FeatureConfig"):
            raise AttributeError(
                "sherpa_onnx.FeatureConfig not available; update sherpa-onnx or "
                "use a build that provides OfflineRecognizer.from_transducer()."
            )

        # Configure the offline transducer. File names must match the download.
        feat_config = sherpa_onnx.FeatureConfig(
            sample_rate=self._sample_rate,
            feature_dim=80,
        )
        model_kwargs = {
            "transducer": sherpa_onnx.OfflineTransducerModelConfig(
                encoder=os.path.join(model_dir, "encoder.int8.onnx"),
                decoder=os.path.join(model_dir, "decoder.int8.onnx"),
                joiner=os.path.join(model_dir, "joiner.int8.onnx"),
            ),
            "tokens": os.path.join(model_dir, "tokens.txt"),
            "num_threads": 2,
            "debug": False,
        }
        if "provider" in inspect.signature(sherpa_onnx.OfflineModelConfig).parameters:
            model_kwargs["provider"] = self._device

        model_config = sherpa_onnx.OfflineModelConfig(**model_kwargs)
        return sherpa_onnx.OfflineRecognizer(
            model_config=model_config,
            feat_config=feat_config,
        )

    def cleanup(self) -> None:
        # ONNX Runtime manages its own memory, but we can help by deleting the object
        del self._recognizer
