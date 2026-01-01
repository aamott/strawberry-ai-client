"""Configuration settings models using Pydantic."""

from typing import Optional, List, Literal
from pydantic import BaseModel, Field
import uuid


class DeviceSettings(BaseModel):
    """Device identification settings."""
    name: str = "Strawberry Spoke"
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])


class HubSettings(BaseModel):
    """Hub connection settings."""
    url: str = "http://localhost:8000"
    token: Optional[str] = None
    timeout_seconds: float = 30.0


class AudioSettings(BaseModel):
    """Audio input/output settings."""
    backend: Literal["sounddevice", "pvrecorder"] = "sounddevice"
    sample_rate: int = 16000
    frame_length_ms: int = 30
    input_device: Optional[int] = None  # None = default device
    output_device: Optional[int] = None


class WakeWordSettings(BaseModel):
    """Wake word detection settings."""
    backend: Literal["porcupine"] = "porcupine"
    keywords: List[str] = ["jarvis"]
    sensitivity: float = 0.5
    enabled: bool = True


class VADConfig(BaseModel):
    """VAD algorithm configuration."""
    max_buffer: float = 2.0
    initial_buffer: float = 1.5
    base_decay: float = 1.0
    growth_rate: float = 2.0
    long_talk_threshold: float = 8.0
    decay_multiplier_rate: float = 0.5


class VADSettings(BaseModel):
    """Voice Activity Detection settings."""
    backend: Literal["silero", "cobra"] = "silero"
    threshold: float = 0.5
    config: VADConfig = Field(default_factory=VADConfig)


class STTSettings(BaseModel):
    """Speech-to-Text settings."""
    backend: Literal["google", "leopard"] = "google"
    language: str = "en-US"


class TTSSettings(BaseModel):
    """Text-to-Speech settings."""
    backend: Literal["orca", "google"] = "orca"
    voice: Optional[str] = None  # Backend-specific voice ID


class SkillsSettings(BaseModel):
    """Skill runner settings."""
    path: str = "./skills"
    sandbox_timeout_seconds: float = 5.0


class VoiceSettings(BaseModel):
    """Voice interaction settings."""
    audio_feedback_enabled: bool = True
    push_to_talk_enabled: bool = True
    push_to_talk_key: str = "Ctrl+Space"  # Keyboard shortcut


class UISettings(BaseModel):
    """User interface settings."""
    theme: Literal["dark", "light", "system"] = "dark"
    start_minimized: bool = False
    show_waveform: bool = True


class Settings(BaseModel):
    """Root configuration model."""
    device: DeviceSettings = Field(default_factory=DeviceSettings)
    hub: HubSettings = Field(default_factory=HubSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    wake_word: WakeWordSettings = Field(default_factory=WakeWordSettings)
    vad: VADSettings = Field(default_factory=VADSettings)
    stt: STTSettings = Field(default_factory=STTSettings)
    tts: TTSSettings = Field(default_factory=TTSSettings)
    skills: SkillsSettings = Field(default_factory=SkillsSettings)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    ui: UISettings = Field(default_factory=UISettings)
    
    class Config:
        extra = "ignore"  # Ignore unknown fields in config file

