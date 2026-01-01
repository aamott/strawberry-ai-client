"""Tests for configuration system."""

import os
import tempfile
from pathlib import Path

# Add src to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from strawberry.config.settings import (
    Settings, AudioSettings, VADConfig, LLMConfig, ConversationConfig
)
from strawberry.config.loader import load_config, get_settings, reset_settings


def test_default_settings():
    """Settings should have sensible defaults."""
    settings = Settings()
    
    assert settings.audio.sample_rate == 16000
    assert settings.audio.backend == "sounddevice"
    assert settings.wake_word.keywords == ["jarvis"]
    assert settings.vad.backend == "silero"


def test_settings_override():
    """Settings should allow overriding defaults."""
    settings = Settings(
        audio=AudioSettings(sample_rate=48000, backend="pvrecorder")
    )
    
    assert settings.audio.sample_rate == 48000
    assert settings.audio.backend == "pvrecorder"
    # Other defaults should remain
    assert settings.vad.backend == "silero"


def test_vad_config_defaults():
    """VAD config should have correct defaults."""
    config = VADConfig()
    
    assert config.max_buffer == 2.0
    assert config.initial_buffer == 1.5
    assert config.growth_rate == 2.0
    assert config.long_talk_threshold == 8.0


def test_load_yaml_config():
    """Should load settings from YAML file."""
    reset_settings()
    
    yaml_content = """
device:
  name: "Test Device"
audio:
  sample_rate: 44100
  backend: pvrecorder
"""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(yaml_content)
        config_path = Path(f.name)
    
    try:
        settings = load_config(config_path=config_path)
        
        assert settings.device.name == "Test Device"
        assert settings.audio.sample_rate == 44100
        assert settings.audio.backend == "pvrecorder"
        # Defaults should still work
        assert settings.wake_word.keywords == ["jarvis"]
    finally:
        config_path.unlink()
        reset_settings()


def test_env_var_expansion():
    """Should expand ${VAR} patterns from environment."""
    reset_settings()
    
    # Set test env var
    os.environ["TEST_HUB_TOKEN"] = "secret123"
    
    yaml_content = """
hub:
  token: "${TEST_HUB_TOKEN}"
  url: "http://testhost:8000"
"""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(yaml_content)
        config_path = Path(f.name)
    
    try:
        settings = load_config(config_path=config_path)
        
        assert settings.hub.token == "secret123"
        assert settings.hub.url == "http://testhost:8000"
    finally:
        config_path.unlink()
        del os.environ["TEST_HUB_TOKEN"]
        reset_settings()


def test_get_settings_returns_defaults():
    """get_settings() should return defaults if not loaded."""
    reset_settings()
    
    settings = get_settings()
    
    assert settings is not None
    assert settings.audio.sample_rate == 16000


def test_device_id_auto_generated():
    """Device ID should be auto-generated if not provided."""
    settings = Settings()
    
    assert settings.device.id is not None
    assert len(settings.device.id) == 8  # UUID first 8 chars


def test_llm_config_defaults():
    """LLM config should have sensible defaults."""
    config = LLMConfig()
    
    assert config.temperature == 0.7
    assert config.max_tokens == 1000
    assert config.top_p == 1.0
    assert config.presence_penalty == 0.0
    assert config.frequency_penalty == 0.0


def test_conversation_config_defaults():
    """Conversation config should have sensible defaults."""
    config = ConversationConfig()
    
    assert config.max_history == 50
    assert config.max_tokens == 8000
    assert config.timeout_minutes == 30


def test_settings_include_llm_and_conversation():
    """Settings should include LLM and conversation configs."""
    settings = Settings()
    
    assert hasattr(settings, 'llm')
    assert hasattr(settings, 'conversation')
    assert settings.llm.temperature == 0.7
    assert settings.conversation.max_history == 50


def test_llm_config_override():
    """LLM config should be overridable."""
    settings = Settings(
        llm=LLMConfig(temperature=0.5, max_tokens=500)
    )
    
    assert settings.llm.temperature == 0.5
    assert settings.llm.max_tokens == 500


def test_conversation_config_override():
    """Conversation config should be overridable."""
    settings = Settings(
        conversation=ConversationConfig(max_history=100, timeout_minutes=60)
    )
    
    assert settings.conversation.max_history == 100
    assert settings.conversation.timeout_minutes == 60

