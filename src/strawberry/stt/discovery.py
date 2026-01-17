"""Module discovery for STT providers.

This module provides functions to dynamically discover and load
STT engine implementations from the backends directory.
"""

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Dict, Type

from .base import STTEngine

logger = logging.getLogger(__name__)


def discover_stt_modules() -> Dict[str, Type[STTEngine]]:
    """Scan the stt/backends directory for STTEngine subclasses.
    
    Discovers all modules in the backends directory that contain
    classes inheriting from STTEngine.
    
    Returns:
        Dictionary mapping module names to STTEngine subclasses.
        Example: {"leopard": LeopardSTT, "mock": MockSTT}
    """
    modules: Dict[str, Type[STTEngine]] = {}
    backends_path = Path(__file__).parent / "backends"
    
    if not backends_path.exists():
        logger.warning(f"STT backends directory not found: {backends_path}")
        return modules
    
    for finder, name, ispkg in pkgutil.iter_modules([str(backends_path)]):
        # Skip __pycache__ and private modules
        if name.startswith("_"):
            continue
            
        try:
            module = importlib.import_module(f"strawberry.stt.backends.{name}")
            
            # Find STTEngine subclasses in the module
            for attr_name in dir(module):
                obj = getattr(module, attr_name)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, STTEngine)
                    and obj is not STTEngine
                ):
                    modules[name] = obj
                    logger.debug(f"Discovered STT module: {name} -> {obj.__name__}")
                    break  # One STT class per module
                    
        except ImportError as e:
            logger.warning(f"Failed to import STT module '{name}': {e}")
        except Exception as e:
            logger.error(f"Error loading STT module '{name}': {e}")
    
    return modules


def get_stt_module(name: str) -> Type[STTEngine] | None:
    """Get a specific STT module by name.
    
    Args:
        name: Module name (e.g., "leopard", "mock")
        
    Returns:
        The STTEngine subclass, or None if not found
    """
    modules = discover_stt_modules()
    return modules.get(name)


def list_stt_modules() -> list[dict]:
    """List all available STT modules with their metadata.
    
    Returns:
        List of dictionaries with module info:
        [{"name": "leopard", "display_name": "Leopard (Picovoice)", "description": "..."}]
    """
    modules = discover_stt_modules()
    result = []
    
    for module_name, cls in modules.items():
        result.append({
            "name": module_name,
            "display_name": getattr(cls, "name", module_name),
            "description": getattr(cls, "description", ""),
            "has_settings": len(cls.get_settings_schema()) > 0,
        })
    
    return result
