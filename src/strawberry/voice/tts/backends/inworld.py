"""Inworld AI TTS backend.

Docs: https://docs.inworld.ai/docs/quickstart-tts
"""

from __future__ import annotations

import base64
import os
import wave
from io import BytesIO
from typing import ClassVar, List

import numpy as np
import requests

from ..base import AudioChunk, TTSEngine

_INWORLD_AVAILABLE = True
_INWORLD_IMPORT_ERROR: str | None = None


class InworldTTS(TTSEngine):
    """Text-to-Speech via Inworld AI REST API."""

    name: ClassVar[str] = "Inworld AI TTS"
    description: ClassVar[str] = "Cloud TTS via Inworld AI voice API"

    DEFAULT_URL: ClassVar[str] = "https://api.inworld.ai/tts/v1/voice"
    DEFAULT_MODEL_ID: ClassVar[str] = "inworld-tts-1.5-max"
    DEFAULT_SAMPLE_RATE: ClassVar[int] = 24000

    @classmethod
    def is_healthy(cls) -> bool:
        return _INWORLD_AVAILABLE

    @classmethod
    def health_check_error(cls) -> str | None:
        return _INWORLD_IMPORT_ERROR

    @classmethod
    def get_settings_schema(cls) -> List:
        from strawberry.shared.settings import FieldType, SettingField

        return [
            SettingField(
                key="api_key",
                label="Inworld API Key",
                type=FieldType.PASSWORD,
                secret=True,
                env_key="INWORLD_API_KEY",
                description="API key for Inworld TTS",
                metadata={
                    "api_key_url": "https://docs.inworld.ai/docs/quickstart-tts",
                },
            ),
            SettingField(
                key="voice_id",
                label="Voice ID",
                type=FieldType.TEXT,
                default="Ashley",
                description="Inworld voice id",
            ),
            SettingField(
                key="model_id",
                label="Model ID",
                type=FieldType.TEXT,
                default=cls.DEFAULT_MODEL_ID,
                description="Inworld TTS model id",
            ),
            SettingField(
                key="sample_rate",
                label="Sample Rate",
                type=FieldType.SELECT,
                options=["16000", "22050", "24000", "44100", "48000"],
                default=str(cls.DEFAULT_SAMPLE_RATE),
                description="Requested PCM sample rate",
            ),
            SettingField(
                key="url",
                label="Endpoint URL",
                type=FieldType.TEXT,
                default=cls.DEFAULT_URL,
                description="Inworld TTS endpoint URL",
            ),
        ]

    def __init__(
        self,
        api_key: str | None = None,
        voice_id: str = "Ashley",
        model_id: str = DEFAULT_MODEL_ID,
        sample_rate: int | str = DEFAULT_SAMPLE_RATE,
        url: str = DEFAULT_URL,
    ) -> None:
        if api_key is None:
            api_key = os.environ.get("INWORLD_API_KEY")

        if not api_key:
            raise ValueError(
                "INWORLD_API_KEY required. Set it in .env or pass api_key parameter."
            )

        self._api_key = api_key
        self._voice_id = (voice_id or "Ashley").strip()
        self._model_id = (model_id or self.DEFAULT_MODEL_ID).strip()
        self._sample_rate_val = int(sample_rate)
        self._url = (url or self.DEFAULT_URL).strip()

    @property
    def sample_rate(self) -> int:
        return self._sample_rate_val

    def synthesize(self, text: str) -> AudioChunk:
        if not text or not text.strip():
            return AudioChunk(
                audio=np.array([], dtype=np.int16),
                sample_rate=self.sample_rate,
            )

        payload = {
            "text": text,
            "voiceId": self._voice_id,
            "modelId": self._model_id,
            "audioConfig": {
                "audioEncoding": "LINEAR16",
                "sampleRateHertz": self._sample_rate_val,
            },
        }
        headers = {
            "Authorization": f"Basic {self._api_key}",
            "Content-Type": "application/json",
        }

        response = requests.post(self._url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()

        body = response.json()
        audio_b64 = body.get("audioContent")
        if not audio_b64:
            raise RuntimeError("Inworld TTS response missing 'audioContent'")

        raw = base64.b64decode(audio_b64)
        audio, sr = self._decode_audio(raw)
        self._sample_rate_val = sr

        return AudioChunk(audio=audio, sample_rate=sr)

    def _decode_audio(self, raw: bytes) -> tuple[np.ndarray, int]:
        if raw[:4] == b"RIFF":
            with wave.open(BytesIO(raw), "rb") as wav:
                sample_rate = wav.getframerate() or self._sample_rate_val
                channels = wav.getnchannels()
                sampwidth = wav.getsampwidth()
                frames = wav.readframes(wav.getnframes())

            if sampwidth != 2:
                raise RuntimeError(
                    "Inworld returned WAV that is not 16-bit PCM; unsupported format"
                )

            audio = np.frombuffer(frames, dtype=np.int16)
            if channels > 1:
                audio = audio.reshape(-1, channels).mean(axis=1).astype(np.int16)
            return audio, int(sample_rate)

        if raw[:3] == b"ID3" or (
            len(raw) > 1 and raw[0] == 0xFF and (raw[1] & 0xE0) == 0xE0
        ):
            raise RuntimeError(
                "Inworld returned compressed audio. Request PCM/LINEAR16 in audioConfig."
            )

        audio = np.frombuffer(raw, dtype=np.int16)
        return audio, self._sample_rate_val
