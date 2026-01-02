"""Leopard STT backend (Picovoice).

Requires: pip install pvleopard
Also requires a Picovoice access key.
"""

import os
from typing import Optional

import numpy as np

from ..base import STTEngine, TranscriptionResult


class LeopardSTT(STTEngine):
    """Speech-to-Text using Picovoice Leopard.

    Leopard is an on-device speech-to-text engine that:
    - Runs entirely locally (no cloud API calls)
    - Supports multiple languages
    - Provides word-level timestamps

    Pros:
    - Fast, offline operation
    - Good accuracy
    - Word-level confidence scores

    Cons:
    - Requires Picovoice license
    - Model files can be large
    """

    def __init__(
        self,
        access_key: Optional[str] = None,
        model_path: Optional[str] = None,
    ):
        """Initialize Leopard STT.

        Args:
            access_key: Picovoice access key. If None, reads from
                       PICOVOICE_API_KEY environment variable.
            model_path: Path to custom model file. If None, uses default.

        Raises:
            ImportError: If pvleopard is not installed
            ValueError: If access_key is not provided
        """
        if access_key is None:
            access_key = os.environ.get("PICOVOICE_API_KEY")

        if not access_key:
            raise ValueError(
                "Picovoice access key required. Set PICOVOICE_API_KEY "
                "environment variable or pass access_key parameter."
            )

        import pvleopard

        if model_path:
            self._leopard = pvleopard.create(
                access_key=access_key,
                model_path=model_path,
            )
        else:
            self._leopard = pvleopard.create(access_key=access_key)

        self._sample_rate_val = self._leopard.sample_rate

    @property
    def sample_rate(self) -> int:
        return self._sample_rate_val

    def transcribe(self, audio: np.ndarray) -> TranscriptionResult:
        """Transcribe audio buffer.

        Args:
            audio: Audio samples (int16)

        Returns:
            Transcription result with text and word-level details
        """
        transcript, words = self._leopard.process(audio)

        # Calculate average confidence from word confidences
        if words:
            confidence = sum(w.confidence for w in words) / len(words)
            word_list = [
                {
                    "word": w.word,
                    "start_sec": w.start_sec,
                    "end_sec": w.end_sec,
                    "confidence": w.confidence,
                }
                for w in words
            ]
        else:
            confidence = 0.0
            word_list = []

        return TranscriptionResult(
            text=transcript,
            confidence=confidence,
            is_final=True,
            words=word_list,
        )

    def transcribe_file(self, file_path: str) -> TranscriptionResult:
        """Transcribe audio file.

        Leopard has native file support which may be more efficient.
        """
        transcript, words = self._leopard.process_file(file_path)

        if words:
            confidence = sum(w.confidence for w in words) / len(words)
            word_list = [
                {
                    "word": w.word,
                    "start_sec": w.start_sec,
                    "end_sec": w.end_sec,
                    "confidence": w.confidence,
                }
                for w in words
            ]
        else:
            confidence = 0.0
            word_list = []

        return TranscriptionResult(
            text=transcript,
            confidence=confidence,
            is_final=True,
            words=word_list,
        )

    def cleanup(self) -> None:
        """Release Leopard resources."""
        if self._leopard is not None:
            self._leopard.delete()
            self._leopard = None

