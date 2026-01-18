"""Module discovery for wake word providers.

This module provides functions to dynamically discover and load
wake word detector implementations from the backends directory.
"""

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Dict, Type

from .base import WakeWordDetector

logger = logging.getLogger(__name__)


def discover_wake_modules() -> Dict[str, Type[WakeWordDetector]]:
    """Scan the wake/backends directory for WakeWordDetector subclasses.
    
    Returns:
        Dictionary mapping module names to WakeWordDetector subclasses.
        Example: {"porcupine": PorcupineDetector, "mock": MockWakeWordDetector}
    """
    modules: Dict[str, Type[WakeWordDetector]] = {}
    backends_path = Path(__file__).parent / "backends"
    
    if not backends_path.exists():
        logger.warning(f"Wake backends directory not found: {backends_path}")
        return modules
    
    for finder, name, ispkg in pkgutil.iter_modules([str(backends_path)]):
        if name.startswith("_"):
            continue
            
        try:
            module = importlib.import_module(f"strawberry.wake.backends.{name}")
            
            for attr_name in dir(module):
                obj = getattr(module, attr_name)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, WakeWordDetector)
                    and obj is not WakeWordDetector
                ):
                    modules[name] = obj
                    logger.debug(f"Discovered wake module: {name} -> {obj.__name__}")
                    break
                    
        except ImportError as e:
            logger.warning(f"Failed to import wake module '{name}': {e}")
        except Exception as e:
            logger.error(f"Error loading wake module '{name}': {e}")
    
    return modules


def get_wake_module(name: str) -> Type[WakeWordDetector] | None:
    """Get a specific wake word module by name."""
    modules = discover_wake_modules()
    return modules.get(name)


def list_wake_modules() -> list[dict]:
    """List all available wake word modules with their metadata."""
    modules = discover_wake_modules()
    result = []
    
    for module_name, cls in modules.items():
        result.append({
            "name": module_name,
            "display_name": getattr(cls, "name", module_name),
            "description": getattr(cls, "description", ""),
            "has_settings": len(cls.get_settings_schema()) > 0,
        })
    
    return result
