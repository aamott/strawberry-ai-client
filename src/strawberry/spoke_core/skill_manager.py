"""SkillManager — facade over SkillService for SpokeCore.

Centralizes skill lifecycle (load, enable/disable, summaries) and
deterministic tool hooks so that ``app.py`` stays focused on session
management and routing.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from .events import (
    CoreEvent,
    MessageAdded,
    SkillsLoaded,
    SkillStatusChanged,
    ToolCallResult,
    ToolCallStarted,
)

if TYPE_CHECKING:
    from ..skills.service import SkillService
    from .session import ChatSession

logger = logging.getLogger(__name__)


class SkillManager:
    """Facade wrapping SkillService with event emission.

    Owns:
    - Skill loading and initialization
    - Enable / disable with event broadcast
    - Summaries and load-failure queries
    - System prompt access
    - Deterministic tool hooks (testing only)
    """

    def __init__(
        self,
        skills_path: Path,
        use_sandbox: bool,
        device_name: str,
        allow_unsafe_exec: bool,
        custom_system_prompt: Optional[str],
        emit: Callable[[CoreEvent], Any],
        settings_manager: Optional[Any] = None,
    ) -> None:
        """Initialize the SkillManager.

        Args:
            skills_path: Directory containing skill repos.
            use_sandbox: Whether to use the Pyodide sandbox.
            device_name: Device name for prompt generation.
            allow_unsafe_exec: Allow unsafe direct execution.
            custom_system_prompt: Optional override for the system prompt.
            emit: Async callback to emit CoreEvent instances.
            settings_manager: Optional SettingsManager for skill settings.
        """
        from ..skills.service import SkillService

        self._emit = emit
        self._service = SkillService(
            skills_path=skills_path,
            use_sandbox=use_sandbox,
            device_name=device_name,
            allow_unsafe_exec=allow_unsafe_exec,
            custom_system_prompt=custom_system_prompt,
            settings_manager=settings_manager,
        )

    @property
    def service(self) -> "SkillService":
        """Access the underlying SkillService."""
        return self._service

    # -- lifecycle ------------------------------------------------------------

    async def load_and_emit(
        self,
        on_skill_loaded: Optional[Callable] = None,
    ) -> None:
        """Load skills and emit a SkillsLoaded event.

        Args:
            on_skill_loaded: Optional callback per skill.
                Signature: (skill_name, source, elapsed_ms).
        """
        self._service.load_skills(on_skill_loaded=on_skill_loaded)
        await self._emit(
            SkillsLoaded(
                skills=self._service.get_skill_summaries(),
                failures=self._service.get_load_failures(),
            )
        )

    async def shutdown(self) -> None:
        """Shut down the underlying skill service."""
        await self._service.shutdown()

    # -- queries --------------------------------------------------------------

    def get_summaries(self) -> List[Dict[str, Any]]:
        """Get plain-dict summaries of all loaded skills.

        Returns:
            List of dicts with keys: name, method_count, enabled, source, methods.
        """
        return self._service.get_skill_summaries()

    def get_load_failures(self) -> List[Dict[str, str]]:
        """Get plain-dict list of skills that failed to load.

        Returns:
            List of dicts with keys: source, error.
        """
        return self._service.get_load_failures()

    def get_system_prompt(self) -> str:
        """Get the current system prompt."""
        return self._service.get_system_prompt()

    def set_custom_system_prompt(self, prompt: Optional[str]) -> None:
        """Update the custom system prompt at runtime."""
        self._service.set_custom_system_prompt(prompt)

    # -- enable / disable -----------------------------------------------------

    async def set_enabled(self, name: str, enabled: bool) -> bool:
        """Enable or disable a skill and emit a status change event.

        Args:
            name: Skill class name.
            enabled: True to enable, False to disable.

        Returns:
            True if the skill was found and status changed.
        """
        ok = (
            self._service.enable_skill(name)
            if enabled
            else self._service.disable_skill(name)
        )
        if ok:
            await self._emit(SkillStatusChanged(skill_name=name, enabled=enabled))
        return ok

    # -- deterministic tool hooks (testing) -----------------------------------

    async def run_deterministic_hooks(
        self, session: "ChatSession", text: str
    ) -> Optional[str]:
        """Execute deterministic tool hooks if the message matches patterns.

        These hooks are only active when ``testing.deterministic_tool_hooks``
        is enabled.  They let tests exercise specific tools without going
        through the full LLM loop.

        Args:
            session: Current chat session.
            text: User message text.

        Returns:
            Result content if a hook fired and produced a final response,
            otherwise ``None`` (meaning the normal agent loop should run).
        """
        # Hook 1: explicit search_skills request
        if "search_skills" in text.lower() and "use" in text.lower():
            await self._run_search_skills_hook(session)
            return None  # continue to agent loop with enriched context

        # Hook 2: explicit python_exec request
        normalized = text.lower()
        if "python_exec" in normalized and "must" in normalized and "use" in normalized:
            return await self._run_python_exec_hook(session, text)

        return None

    async def _run_search_skills_hook(self, session: "ChatSession") -> None:
        """Inject a search_skills tool result into the session."""
        await self._emit(
            ToolCallStarted(
                session_id=session.id,
                tool_name="search_skills",
                arguments={"query": ""},
            )
        )
        result = await self._service.execute_tool_async(
            "search_skills", {"query": ""}
        )
        success = "error" not in result
        result_text = result.get("result", result.get("error", ""))
        await self._emit(
            ToolCallResult(
                session_id=session.id,
                tool_name="search_skills",
                success=success,
                result=result_text if success else None,
                error=result_text if not success else None,
            )
        )
        tool_msg = (
            f"[Tool: search_skills]\n{result_text}\n\n"
            "[Now respond naturally to the user based on this result. "
            "Do not rerun the same tool call again unless the user asks. ]"
        )
        session.add_message("user", tool_msg)

    async def _run_python_exec_hook(
        self, session: "ChatSession", text: str
    ) -> Optional[str]:
        """Inject a python_exec tool result; returns the result content."""
        match = re.search(r"(device\.[A-Za-z0-9_\.]+\([^\)]*\))", text)
        if not match:
            return None

        code = f"print({match.group(1)})"
        await self._emit(
            ToolCallStarted(
                session_id=session.id,
                tool_name="python_exec",
                arguments={"code": code},
            )
        )
        result = await self._service.execute_tool_async(
            "python_exec", {"code": code}
        )
        success = "error" not in result
        result_text = result.get("result", result.get("error", ""))
        await self._emit(
            ToolCallResult(
                session_id=session.id,
                tool_name="python_exec",
                success=success,
                result=result_text if success else None,
                error=result_text if not success else None,
            )
        )
        session.add_message("assistant", result_text)
        await self._emit(
            MessageAdded(
                session_id=session.id,
                role="assistant",
                content=result_text,
            )
        )
        return result_text
