"""Module discovery for VAD providers.

This module provides functions to dynamically discover and load
VAD backend implementations from the backends directory.
"""

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Dict, Type

from .base import VADBackend

logger = logging.getLogger(__name__)


def discover_vad_modules() -> Dict[str, Type[VADBackend]]:
    """Scan the vad/backends directory for VADBackend subclasses.
    
    Returns:
        Dictionary mapping module names to VADBackend subclasses.
        Example: {"silero": SileroVAD, "mock": MockVAD}
    """
    modules: Dict[str, Type[VADBackend]] = {}
    backends_path = Path(__file__).parent / "backends"

    if not backends_path.exists():
        logger.warning(f"VAD backends directory not found: {backends_path}")
        return modules

    for finder, name, ispkg in pkgutil.iter_modules([str(backends_path)]):
        if name.startswith("_"):
            continue

        try:
            module = importlib.import_module(f"strawberry.vad.backends.{name}")

            for attr_name in dir(module):
                obj = getattr(module, attr_name)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, VADBackend)
                    and obj is not VADBackend
                ):
                    modules[name] = obj
                    logger.debug(f"Discovered VAD module: {name} -> {obj.__name__}")
                    break

        except ImportError as e:
            logger.warning(f"Failed to import VAD module '{name}': {e}")
        except Exception as e:
            logger.error(f"Error loading VAD module '{name}': {e}")

    return modules


def get_vad_module(name: str) -> Type[VADBackend] | None:
    """Get a specific VAD module by name."""
    modules = discover_vad_modules()
    return modules.get(name)


def list_vad_modules() -> list[dict]:
    """List all available VAD modules with their metadata."""
    modules = discover_vad_modules()
    result = []

    for module_name, cls in modules.items():
        result.append({
            "name": module_name,
            "display_name": getattr(cls, "name", module_name),
            "description": getattr(cls, "description", ""),
            "has_settings": len(cls.get_settings_schema()) > 0,
        })

    return result
