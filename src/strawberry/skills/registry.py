"""Skill registry for managing local and remote skills."""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..hub import HubClient
from .loader import SkillInfo, SkillLoader

logger = logging.getLogger(__name__)


@dataclass
class RegistrationResult:
    """Result of skill registration."""

    success: bool
    message: str
    skill_count: int = 0


class SkillRegistry:
    """Manages skill loading and Hub registration.

    Handles:
    - Loading skills from local Python files
    - Registering skills with the Hub
    - Periodic heartbeat to keep skills alive
    - Searching for skills (local and remote)
    """

    def __init__(
        self,
        skills_path: Path,
        hub_client: Optional[HubClient] = None,
        heartbeat_interval: float = 300.0,  # 5 minutes
    ):
        """Initialize skill registry.

        Args:
            skills_path: Path to skills directory
            hub_client: Optional Hub client for remote registration
            heartbeat_interval: Seconds between heartbeats
        """
        self.skills_path = Path(skills_path)
        self.hub_client = hub_client
        self.heartbeat_interval = heartbeat_interval

        self._loader = SkillLoader(skills_path)
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._registered = False

    def load_skills(self) -> List[SkillInfo]:
        """Load all skills from the skills directory.

        Returns:
            List of loaded SkillInfo objects
        """
        return self._loader.load_all()

    async def register_with_hub(self) -> RegistrationResult:
        """Register loaded skills with the Hub.

        Returns:
            RegistrationResult with success status
        """
        if not self.hub_client:
            return RegistrationResult(
                success=False,
                message="No Hub client configured",
            )

        skills_data = self._loader.get_registration_data()

        if not skills_data:
            return RegistrationResult(
                success=True,
                message="No skills to register",
                skill_count=0,
            )

        try:
            result = await self.hub_client.register_skills(skills_data)
            self._registered = True

            logger.info(f"Registered {len(skills_data)} skills with Hub")

            return RegistrationResult(
                success=True,
                message=result.get("message", "Skills registered"),
                skill_count=len(skills_data),
            )
        except Exception as e:
            logger.error(f"Failed to register skills: {e}")
            return RegistrationResult(
                success=False,
                message=str(e),
            )

    async def start_heartbeat(self):
        """Start the heartbeat task to keep skills alive."""
        if self._heartbeat_task is not None:
            return

        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info("Started skill heartbeat")

    async def stop_heartbeat(self):
        """Stop the heartbeat task."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
            logger.info("Stopped skill heartbeat")

    async def _heartbeat_loop(self):
        """Send periodic heartbeats to Hub."""
        while True:
            try:
                await asyncio.sleep(self.heartbeat_interval)

                if self.hub_client and self._registered:
                    await self.hub_client.heartbeat()
                    logger.debug("Sent skill heartbeat")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat failed: {e}")

    async def search_skills(self, query: str = "") -> List[Dict[str, Any]]:
        """Search for skills locally and remotely.

        Args:
            query: Search query string

        Returns:
            List of matching skills
        """
        results = []

        # Local skills
        local_skills = self._loader.get_all_skills()
        for skill in local_skills:
            for method in skill.methods:
                # Simple substring matching
                if (
                    not query
                    or query.lower() in method.name.lower()
                    or query.lower() in skill.name.lower()
                    or (method.docstring and query.lower() in method.docstring.lower())
                ):
                    results.append(
                        {
                            "path": f"{skill.name}.{method.name}",
                            "signature": method.signature,
                            "summary": (method.docstring or "").split("\n")[0],
                            "device": "local",
                            "is_local": True,
                        }
                    )

        # Remote skills from Hub
        if self.hub_client:
            try:
                remote_results = await self.hub_client.search_skills(query)
                for r in remote_results:
                    r["is_local"] = False
                    results.append(r)
            except Exception as e:
                logger.error(f"Failed to search remote skills: {e}")

        return results

    def get_skill(self, name: str) -> Optional[SkillInfo]:
        """Get a local skill by name."""
        return self._loader.get_skill(name)

    def call_skill(self, skill_name: str, method_name: str, *args, **kwargs) -> Any:
        """Call a local skill method.

        Args:
            skill_name: Name of the skill class
            method_name: Name of the method
            *args, **kwargs: Method arguments

        Returns:
            Method return value
        """
        return self._loader.call_method(skill_name, method_name, *args, **kwargs)

    def format_skills_prompt(self) -> str:
        """Format loaded skills as a prompt for the LLM.

        Returns:
            Formatted string describing available skills
        """
        skills = self._loader.get_all_skills()

        if not skills:
            return "No skills are currently loaded."

        lines = ["# Available Skills", ""]

        for skill in skills:
            lines.append(f"## {skill.name}")
            if skill.class_obj.__doc__:
                lines.append(skill.class_obj.__doc__.strip())
            lines.append("")

            for method in skill.methods:
                lines.append(f"### `{method.signature}`")
                if method.docstring:
                    lines.append(method.docstring)
                lines.append("")

        return "\n".join(lines)
