"""Skill loading and management."""

from .loader import SkillLoader, SkillInfo
from .registry import SkillRegistry
from .service import SkillService, SkillCallResult
from .remote import (
    DeviceManager,
    RemoteSkillResult,
    REMOTE_MODE_PROMPT,
    LOCAL_MODE_PROMPT,
    SWITCHED_TO_REMOTE_PROMPT,
    SWITCHED_TO_LOCAL_PROMPT,
)
from .sandbox import SandboxExecutor, SandboxConfig, Gatekeeper, ProxyGenerator

__all__ = [
    # Core
    "SkillLoader",
    "SkillInfo",
    "SkillRegistry",
    "SkillService",
    "SkillCallResult",
    # Remote mode
    "DeviceManager",
    "RemoteSkillResult",
    "REMOTE_MODE_PROMPT",
    "LOCAL_MODE_PROMPT",
    "SWITCHED_TO_REMOTE_PROMPT",
    "SWITCHED_TO_LOCAL_PROMPT",
    # Sandbox
    "SandboxExecutor",
    "SandboxConfig",
    "Gatekeeper",
    "ProxyGenerator",
]

