"""Voice Activity Detection module for Strawberry AI."""

from .base import VADBackend
from .processor import VADConfig, VADProcessor

__all__ = ["VADBackend", "VADProcessor", "VADConfig"]

