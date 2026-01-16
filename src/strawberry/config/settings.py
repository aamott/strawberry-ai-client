"""Configuration settings models using Pydantic."""

import uuid
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


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


class SandboxSettings(BaseModel):
    """Sandbox execution settings."""
    enabled: bool = True  # Use secure sandbox (disable for development)
    timeout_seconds: float = 5.0  # Execution timeout
    memory_limit_mb: int = 128  # Memory limit for sandbox
    deno_path: str = "deno"  # Path to Deno executable


class SkillsSettings(BaseModel):
    """Skill runner settings."""
    path: str = "./skills"
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)


class MediaSettings(BaseModel):
    """Media control settings."""
    macos_player: Literal["spotify", "music"] = "spotify"


class TensorZeroSettings(BaseModel):
    """TensorZero gateway settings."""
    enabled: bool = True  # Use TensorZero for LLM routing
    gateway_url: str = "http://127.0.0.1:3000"
    timeout_seconds: float = 60.0


class LocalLLMSettings(BaseModel):
    """Local LLM fallback settings."""
    enabled: bool = True
    provider: Literal["ollama"] = "ollama"
    model: str = "llama3.2:3b"
    url: str = "http://localhost:11434/v1"


class LLMConfig(BaseModel):
    """Large Language Model configuration."""
    temperature: float = 0.7
    max_tokens: int = 1000
    top_p: float = 1.0
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0


class ConversationConfig(BaseModel):
    """Conversation history management."""
    max_history: int = 50  # Max messages to keep
    max_tokens: int = 8000  # Approximate token limit for context
    timeout_minutes: int = 30  # Session timeout


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


class StorageSettings(BaseModel):
    """Local storage settings."""
    db_path: str = "./data/sessions.db"
    max_local_sessions: int = 100
    auto_sync: bool = True
    sync_interval_seconds: float = 30.0


class Settings(BaseModel):
    """Root configuration model."""
    model_config = ConfigDict(extra="ignore")  # Ignore unknown fields in config file

    device: DeviceSettings = Field(default_factory=DeviceSettings)
    hub: HubSettings = Field(default_factory=HubSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    wake_word: WakeWordSettings = Field(default_factory=WakeWordSettings)
    vad: VADSettings = Field(default_factory=VADSettings)
    stt: STTSettings = Field(default_factory=STTSettings)
    tts: TTSSettings = Field(default_factory=TTSSettings)
    skills: SkillsSettings = Field(default_factory=SkillsSettings)
    media: MediaSettings = Field(default_factory=MediaSettings)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    ui: UISettings = Field(default_factory=UISettings)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    conversation: ConversationConfig = Field(default_factory=ConversationConfig)
    tensorzero: TensorZeroSettings = Field(default_factory=TensorZeroSettings)
    local_llm: LocalLLMSettings = Field(default_factory=LocalLLMSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)

