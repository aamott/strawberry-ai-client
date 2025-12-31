"""Configuration file loader."""

import os
from pathlib import Path
from typing import Optional
import yaml
from dotenv import load_dotenv

from .settings import Settings


# Global settings instance
_settings: Optional[Settings] = None


def _expand_env_vars(obj):
    """Recursively expand ${VAR} patterns in strings."""
    if isinstance(obj, str):
        # Handle ${VAR} pattern
        if obj.startswith("${") and obj.endswith("}"):
            var_name = obj[2:-1]
            return os.environ.get(var_name, "")
        return obj
    elif isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_expand_env_vars(item) for item in obj]
    return obj


def load_config(
    config_path: Optional[Path] = None,
    env_path: Optional[Path] = None,
) -> Settings:
    """Load configuration from YAML file and environment.
    
    Args:
        config_path: Path to config.yaml (default: config/config.yaml)
        env_path: Path to .env file (default: .env)
    
    Returns:
        Loaded Settings instance
    """
    global _settings
    
    # Load .env file if it exists
    if env_path is None:
        env_path = Path(".env")
    if env_path.exists():
        load_dotenv(env_path)
    
    # Load config.yaml
    config_data = {}
    if config_path is None:
        config_path = Path("config/config.yaml")
    
    if config_path.exists():
        with open(config_path) as f:
            config_data = yaml.safe_load(f) or {}
    
    # Expand environment variables
    config_data = _expand_env_vars(config_data)
    
    # Create settings
    _settings = Settings(**config_data)
    
    return _settings


def get_settings() -> Settings:
    """Get the current settings instance.
    
    Loads default settings if not yet loaded.
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reset settings to None (for testing)."""
    global _settings
    _settings = None

