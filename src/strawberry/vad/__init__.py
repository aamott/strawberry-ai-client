"""Voice Activity Detection module for Strawberry AI."""

from .base import VADBackend
from .processor import VADProcessor, VADConfig

__all__ = ["VADBackend", "VADProcessor", "VADConfig"]

