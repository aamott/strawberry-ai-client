"""Google AI Studio (Gemini) Text-to-Speech backend."""

from __future__ import annotations

import logging
import os
from typing import ClassVar, List

import numpy as np

from ..base import AudioChunk, TTSEngine

logger = logging.getLogger(__name__)

# Check for google-genai availability at module load time
_AI_STUDIO_AVAILABLE = False
_AI_STUDIO_IMPORT_ERROR: str | None = None
try:
    from google import genai
    from google.genai import types

    _AI_STUDIO_AVAILABLE = True
except ImportError as e:
    genai = None  # type: ignore[assignment]
    types = None  # type: ignore[assignment]
    _AI_STUDIO_IMPORT_ERROR = (
        f"google-genai not installed. Install with: pip install google-genai. ({e})"
    )


class AIStudioTTS(TTSEngine):
    """Text-to-Speech using Google AI Studio (Gemini) speech generation."""

    name: ClassVar[str] = "Google AI Studio (Gemini) TTS"
    description: ClassVar[str] = (
        "Cloud TTS via Gemini speech-generation models (requires API key)."
    )

    SAMPLE_RATE: ClassVar[int] = 24000
    DEFAULT_MODEL: ClassVar[str] = "gemini-2.5-flash-preview-tts"
    DEFAULT_VOICE: ClassVar[str] = "Kore"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        voice: str = DEFAULT_VOICE,
    ) -> None:
        if api_key is None:
            api_key = os.environ.get("GOOGLE_AI_STUDIO_API_KEY")

        # CLI/UI may save empty strings; treat them as unset.
        if api_key is not None and not str(api_key).strip():
            api_key = None

        if not str(model).strip():
            model = self.DEFAULT_MODEL

        if not str(voice).strip():
            voice = self.DEFAULT_VOICE

        if not api_key:
            raise ValueError(
                "GOOGLE_AI_STUDIO_API_KEY required."
                " Set it in .env or pass api_key parameter."
            )

        if genai is None or types is None:
            raise ImportError(
                "google-genai not installed. Install with: pip install google-genai"
            )

        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._voice = voice

    @classmethod
    def is_healthy(cls) -> bool:
        if not _AI_STUDIO_AVAILABLE:
            return False
        return bool(os.environ.get("GOOGLE_AI_STUDIO_API_KEY"))

    @classmethod
    def health_check_error(cls) -> str | None:
        if not _AI_STUDIO_AVAILABLE:
            return _AI_STUDIO_IMPORT_ERROR
        if not os.environ.get("GOOGLE_AI_STUDIO_API_KEY"):
            return "Missing GOOGLE_AI_STUDIO_API_KEY in environment/.env"
        return None

    @classmethod
    def get_settings_schema(cls) -> List:
        from strawberry.shared.settings import FieldType, SettingField

        return [
            SettingField(
                key="api_key",
                label="Google AI Studio API Key",
                type=FieldType.PASSWORD,
                secret=True,
                env_key="GOOGLE_AI_STUDIO_API_KEY",
                description="API key from Google AI Studio",
                metadata={
                    "api_key_url": "https://aistudio.google.com/apikey",
                },
            ),
            SettingField(
                key="model",
                label="Gemini TTS Model",
                type=FieldType.TEXT,
                default="gemini-2.5-flash-preview-tts",
                description="Gemini model ID for speech generation",
            ),
            SettingField(
                key="voice",
                label="Voice Name",
                type=FieldType.TEXT,
                default="Kore",
                description="Prebuilt voice name (see Gemini TTS docs)",
            ),
        ]

    @property
    def sample_rate(self) -> int:
        return self.SAMPLE_RATE

    def synthesize(self, text: str) -> AudioChunk:
        if not text or not text.strip():
            return AudioChunk(
                audio=np.array([], dtype=np.int16), sample_rate=self.SAMPLE_RATE
            )

        assert types is not None

        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = self._client.models.generate_content(
                    model=self._model,
                    contents=text,
                    config=types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name=self._voice,
                                )
                            )
                        ),
                    ),
                )
                last_error = None
                break
            except Exception as e:
                last_error = e
                msg = str(e)
                retryable = " 500 " in msg or "INTERNAL" in msg
                if retryable and attempt < 3:
                    logger.warning(
                        "AIStudioTTS request failed with transient error; retrying "
                        "(attempt=%s/3, model=%s, voice=%s): %s",
                        attempt,
                        self._model,
                        self._voice,
                        msg,
                    )
                    continue

                logger.error(
                    "AIStudioTTS request failed (attempt=%s/3, model=%s, voice=%s): %s",
                    attempt,
                    self._model,
                    self._voice,
                    msg,
                )
                raise

        if last_error is not None:
            raise last_error

        data = response.candidates[0].content.parts[0].inline_data.data
        pcm = np.frombuffer(data, dtype=np.int16)
        return AudioChunk(audio=pcm, sample_rate=self.SAMPLE_RATE)


if __name__ == "__main__":
    from dotenv import load_dotenv

    from strawberry.utils.paths import get_project_root
    from strawberry.voice.audio.playback import AudioPlayer

    load_dotenv(get_project_root() / ".env", override=True)

    cls = AIStudioTTS
    print("backend=ai_studio", "healthy=", cls.is_healthy())
    if not cls.is_healthy():
        print("health_error=", cls.health_check_error())
        raise SystemExit(1)

    try:
        tts = cls()
    except Exception as e:
        raise SystemExit(f"Failed to init AIStudioTTS: {e}")

    text = "Hello from Google AI Studio TTS. If you hear this, AI Studio playback works."
    chunk = tts.synthesize(text)
    print("samples=", len(chunk.audio), "sample_rate=", chunk.sample_rate)
    if len(chunk.audio) == 0:
        raise SystemExit("AI Studio produced empty audio")
    AudioPlayer(sample_rate=chunk.sample_rate).play(
        chunk.audio,
        sample_rate=chunk.sample_rate,
        blocking=True,
    )
