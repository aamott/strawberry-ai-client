"""Module discovery for TTS providers.

This module provides functions to dynamically discover and load
TTS engine implementations from the backends directory.
"""

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Dict, Type

from .base import TTSEngine

logger = logging.getLogger(__name__)


def discover_tts_modules() -> Dict[str, Type[TTSEngine]]:
    """Scan the tts/backends directory for TTSEngine subclasses.
    
    Discovers all modules in the backends directory that contain
    classes inheriting from TTSEngine.
    
    Returns:
        Dictionary mapping module names to TTSEngine subclasses.
        Example: {"orca": OrcaTTS, "mock": MockTTS}
    """
    modules: Dict[str, Type[TTSEngine]] = {}
    backends_path = Path(__file__).parent / "backends"
    
    if not backends_path.exists():
        logger.warning(f"TTS backends directory not found: {backends_path}")
        return modules
    
    for finder, name, ispkg in pkgutil.iter_modules([str(backends_path)]):
        # Skip __pycache__ and private modules
        if name.startswith("_"):
            continue
            
        try:
            module = importlib.import_module(f"strawberry.tts.backends.{name}")
            
            # Find TTSEngine subclasses in the module
            for attr_name in dir(module):
                obj = getattr(module, attr_name)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, TTSEngine)
                    and obj is not TTSEngine
                ):
                    modules[name] = obj
                    logger.debug(f"Discovered TTS module: {name} -> {obj.__name__}")
                    break  # One TTS class per module
                    
        except ImportError as e:
            logger.warning(f"Failed to import TTS module '{name}': {e}")
        except Exception as e:
            logger.error(f"Error loading TTS module '{name}': {e}")
    
    return modules


def get_tts_module(name: str) -> Type[TTSEngine] | None:
    """Get a specific TTS module by name.
    
    Args:
        name: Module name (e.g., "orca", "mock")
        
    Returns:
        The TTSEngine subclass, or None if not found
    """
    modules = discover_tts_modules()
    return modules.get(name)


def list_tts_modules() -> list[dict]:
    """List all available TTS modules with their metadata.
    
    Returns:
        List of dictionaries with module info:
        [{"name": "orca", "display_name": "Orca (Picovoice)", "description": "..."}]
    """
    modules = discover_tts_modules()
    result = []
    
    for module_name, cls in modules.items():
        result.append({
            "name": module_name,
            "display_name": getattr(cls, "name", module_name),
            "description": getattr(cls, "description", ""),
            "has_settings": len(cls.get_settings_schema()) > 0,
        })
    
    return result
