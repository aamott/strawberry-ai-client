"""Google Cloud Speech-to-Text backend.

Note:
    This backend uses the `google-cloud-speech` client library (Google Cloud
    Speech-to-Text). In many setups this requires service account credentials
    via `GOOGLE_APPLICATION_CREDENTIALS`. A `GOOGLE_AI_STUDIO_API_KEY` is not
    guaranteed to work with Google Cloud Speech-to-Text; if authentication
    fails, VoiceCore should fall back to another STT backend.
"""

import os
from typing import Any, ClassVar, List

import numpy as np

from ..base import STTEngine, TranscriptionResult

try:
    from google.cloud import speech
except ImportError:
    speech = None


class GoogleSTT(STTEngine):
    """Google Cloud Speech-to-Text engine.

    Requires 'google-cloud-speech' package and credentials.
    Credentials can be set via GOOGLE_APPLICATION_CREDENTIALS environment variable
    or GOOGLE_API_KEY.
    """

    name: ClassVar[str] = "Google Cloud STT"
    description: ClassVar[str] = "Online speech recognition using Google Cloud API"

    def __init__(self):
        """Initialize Google STT client."""
        if speech is None:
            raise ImportError(
                "google-cloud-speech not installed. "
                "Install with: pip install google-cloud-speech"
            )

        # Check for API key in env if standard creds aren't set
        client_options = None
        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_AI_STUDIO_API_KEY")
        if api_key and not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            client_options = {"api_key": api_key}

        try:
            self._client = speech.SpeechClient(client_options=client_options)
        except Exception as e:
            # Wrap standard google auth errors
            raise RuntimeError(f"Failed to initialize Google Speech client: {e}") from e

        # Configure recognition config
        self._config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            language_code="en-US",
            # Enable automatic punctuation
            enable_automatic_punctuation=True,
        )

    @property
    def sample_rate(self) -> int:
        return 16000

    def transcribe(self, audio: np.ndarray) -> TranscriptionResult:
        """Transcribe audio buffer."""
        # Convert int16 numpy array to bytes
        content = audio.tobytes()

        audio_payload = speech.RecognitionAudio(content=content)

        try:
            response = self._client.recognize(config=self._config, audio=audio_payload)
        except Exception as e:
            raise RuntimeError(f"Google STT transcription failed: {e}") from e

        # Process results
        full_transcript = []
        confidence = 0.0

        for result in response.results:
            # result.alternatives[0] is the most likely transcript
            if result.alternatives:
                best = result.alternatives[0]
                full_transcript.append(best.transcript)
                confidence = best.confidence

        text = " ".join(full_transcript).strip()

        return TranscriptionResult(
            text=text,
            # Google confidence is 0.0-1.0
            confidence=confidence,
            is_final=True,
            language="en-US",
        )

    @classmethod
    def get_settings_schema(cls) -> List[Any]:
        # No runtime settings for now, uses env vars
        return []
