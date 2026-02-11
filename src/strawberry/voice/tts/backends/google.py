"""Google Cloud Text-to-Speech backend."""

import os
from typing import Any, ClassVar, List

import numpy as np

from ..base import AudioChunk, TTSEngine

# Check for google-cloud-texttospeech availability at module load time
_GOOGLE_TTS_AVAILABLE = False
_GOOGLE_TTS_IMPORT_ERROR: str | None = None
try:
    from google.cloud import texttospeech

    _GOOGLE_TTS_AVAILABLE = True
except ImportError as e:
    texttospeech = None
    _GOOGLE_TTS_IMPORT_ERROR = (
        f"google-cloud-texttospeech not installed. "
        f"Install with: pip install google-cloud-texttospeech. ({e})"
    )


class GoogleTTS(TTSEngine):
    """Google Cloud Text-to-Speech engine.

    Requires 'google-cloud-texttospeech' package and credentials.
    Credentials can be set via GOOGLE_APPLICATION_CREDENTIALS environment variable
    or GOOGLE_API_KEY.
    """

    name: ClassVar[str] = "Google Cloud TTS"
    description: ClassVar[str] = "Online speech synthesis using Google Cloud API"

    @classmethod
    def is_healthy(cls) -> bool:
        """Check if Google Cloud TTS is available.

        Returns:
            True if google-cloud-texttospeech package is installed, False otherwise.
        """
        return _GOOGLE_TTS_AVAILABLE

    @classmethod
    def health_check_error(cls) -> str | None:
        """Return the error message if Google Cloud TTS is not available.

        Returns:
            Error message if google-cloud-texttospeech is not installed, None otherwise.
        """
        return _GOOGLE_TTS_IMPORT_ERROR

    def __init__(self):
        """Initialize Google TTS client."""
        if texttospeech is None:
            raise ImportError(
                "google-cloud-texttospeech not installed. "
                "Install with: pip install google-cloud-texttospeech"
            )

        # Check for API key in env if standard creds aren't set
        client_options = None
        api_key = os.getenv("GOOGLE_API_KEY")
        if api_key and not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            client_options = {"api_key": api_key}

        try:
            self._client = texttospeech.TextToSpeechClient(client_options=client_options)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Google TTS client: {e}") from e

        # Standard voice configuration
        self._voice_params = texttospeech.VoiceSelectionParams(
            language_code="en-US",
            name="en-US-Journey-F",  # Try Journey voice, fallback will happen if invalid
        )

        self._audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=24000,  # Higher quality for TTS
        )

    @property
    def sample_rate(self) -> int:
        return 24000

    def synthesize(self, text: str) -> AudioChunk:
        """Synthesize text to audio."""
        if not text:
            return AudioChunk(
                audio=np.array([], dtype=np.int16), sample_rate=self.sample_rate
            )

        input_text = texttospeech.SynthesisInput(text=text)

        try:
            response = self._client.synthesize_speech(
                input=input_text,
                voice=self._voice_params,
                audio_config=self._audio_config,
            )
        except Exception:
            # Fallback to standard voice if Journey fails (needs specific access)
            if "en-US-Journey" in self._voice_params.name:
                self._voice_params = texttospeech.VoiceSelectionParams(
                    language_code="en-US", ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
                )
                try:
                    response = self._client.synthesize_speech(
                        input=input_text,
                        voice=self._voice_params,
                        audio_config=self._audio_config,
                    )
                except Exception:
                    # Log properly in real app, here checking empty audio handling
                    return AudioChunk(
                        audio=np.array([], dtype=np.int16), sample_rate=self.sample_rate
                    )
            else:
                return AudioChunk(
                    audio=np.array([], dtype=np.int16), sample_rate=self.sample_rate
                )

        # Convert bytes to int16 numpy array
        # Google returns bytes in LINEAR16, which is distinct from int16 array
        audio_data = np.frombuffer(response.audio_content, dtype=np.int16)

        return AudioChunk(audio=audio_data, sample_rate=self.sample_rate)

    @classmethod
    def get_settings_schema(cls) -> List[Any]:
        # No runtime settings for now
        return []


if __name__ == "__main__":
    from dotenv import load_dotenv

    from strawberry.utils.paths import get_project_root
    from strawberry.voice.audio.playback import AudioPlayer

    load_dotenv(get_project_root() / ".env", override=True)

    cls = GoogleTTS
    print("backend=google", "healthy=", cls.is_healthy())
    if not cls.is_healthy():
        print("health_error=", cls.health_check_error())
        raise SystemExit(1)

    try:
        tts = cls()
    except Exception as e:
        raise SystemExit(f"Failed to init GoogleTTS: {e}")

    text = "Hello from Google Cloud TTS. If you hear this, Google playback works."
    chunk = tts.synthesize(text)
    print("samples=", len(chunk.audio), "sample_rate=", chunk.sample_rate)
    if len(chunk.audio) == 0:
        raise SystemExit("Google produced empty audio (credentials/permissions?)")
    AudioPlayer(sample_rate=chunk.sample_rate).play(
        chunk.audio,
        sample_rate=chunk.sample_rate,
        blocking=True,
    )
