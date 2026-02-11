"""Skill service for managing skill lifecycle and LLM integration."""

from __future__ import annotations

import ast
import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    pass

from ..hub import HubClient
from .loader import SkillInfo, SkillLoader, SkillMethod
from .sandbox.executor import SandboxConfig, SandboxExecutor
from .sandbox.gatekeeper import Gatekeeper
from .sandbox.proxy_gen import ProxyGenerator, SkillMode

logger = logging.getLogger(__name__)


def normalize_device_name(name: str) -> str:
    """Normalize device name to valid Python identifier."""
    normalized = name.lower()
    normalized = re.sub(r"[\s\-]+", "_", normalized)
    normalized = re.sub(r"[^a-z0-9_]", "", normalized)
    if normalized and normalized[0].isdigit():
        normalized = "_" + normalized
    return normalized


@dataclass
class SkillCallResult:
    """Result of executing a skill call."""
    success: bool
    result: Any = None
    error: Optional[str] = None


class SkillService:
    """Manages skill loading, registration, and execution.

    Responsibilities:
    - Load skills from Python files
    - Register skills with Hub
    - Send heartbeats to keep skills alive
    - Generate system prompt for LLM
    - Parse and execute skill calls from LLM responses
    """

    # Default system prompt template for skills.
    # Users can override this via the llm.system_prompt setting.
    # The placeholder {skill_descriptions} is replaced at runtime with
    # the full list of loaded skills and their methods.
    DEFAULT_SYSTEM_PROMPT_TEMPLATE = (
        "You are Strawberry, a helpful AI assistant with access to skills on this device.\n"
        "\n"
        "## Available Tools\n"
        "\n"
        "You have exactly 3 tools:\n"
        "1. search_skills(query) - Find skills by keyword "
        "(searches method names and descriptions)\n"
        "2. describe_function(path) - Get full signature for a skill method\n"
        "3. python_exec(code) - Execute Python code that calls skills\n"
        "\n"
        "## How to Call Skills\n"
        "\n"
        "To execute a local skill, use python_exec with code that calls\n"
        "device.<SkillName>.<method>().\n"
        "When connected to the Hub, remote skills are available via "
        "devices.<Device>.<SkillName>.<method>().\n"
        "\n"
        "Examples:\n"
        "- Time: python_exec({{\"code\": \"print(device.TimeSkill.get_current_time())\"}})\n"
        "- Weather: python_exec({{\"code\": \"print(device.WeatherSkill."
        "get_current_weather('Seattle'))\"}})\n"
        "- Calculate: python_exec({{\"code\": \"print(device.CalculatorSkill.add(a=5, b=3))\"}})\n"
        "- Smart home: python_exec({{\"code\": \"print(device.HomeAssistantSkill."
        "HassTurnOn(name='short lamp'))\"}})\n"
        "- Remote: python_exec({{\"code\": \"print(devices.living_room_pc."
        "MediaControlSkill.set_volume(level=20))\"}})\n"
        "\n"
        "## Searching Tips\n"
        "\n"
        "search_skills matches against method names and descriptions.\n"
        "Search by **action** or **verb**, not by specific entity/object names.\n"
        "- To turn on a lamp, search 'turn on' not 'lamp'.\n"
        "- To set brightness, search 'light' or 'brightness'.\n"
        "- To look up docs, search 'documentation' or 'query'.\n"
        "\n"
        "If you already see the right skill in Available Skills below, skip search_skills\n"
        "and call describe_function or python_exec directly.\n"
        "\n"
        "## Available Skills\n"
        "\n"
        "{skill_descriptions}\n"
        "\n"
        "## Rules\n"
        "\n"
        "1. Use python_exec to call skills - do NOT call skill methods directly as tools.\n"
        "2. Do NOT output code blocks or ```tool_outputs``` - use actual tool calls.\n"
        "3. Keep responses concise and friendly.\n"
        "4. If you need a skill result, call python_exec with the appropriate code.\n"
        "5. Do NOT ask the user for permission to use skills/tools. Use them when needed.\n"
        "6. Do NOT rerun the same tool call to double-check; use the first result.\n"
        "7. After tool calls complete, ALWAYS provide a final natural-language answer.\n"
        "8. If a tool call fails with 'Unknown tool', immediately switch to python_exec "
        "and proceed.\n"
        "9. For smart-home commands (turn on/off, lights, locks, media), look for "
        "HomeAssistantSkill. Pass the device/entity name as the 'name' kwarg."
    )

    def __init__(
        self,
        skills_path: Path,
        hub_client: Optional[HubClient] = None,
        heartbeat_interval: float = 300.0,  # 5 minutes
        use_sandbox: bool = True,
        sandbox_config: Optional[SandboxConfig] = None,
        device_name: Optional[str] = None,
        allow_unsafe_exec: Optional[bool] = None,
        custom_system_prompt: Optional[str] = None,
    ):
        """Initialize skill service.

        Args:
            skills_path: Path to skills directory
            hub_client: Hub client for registration (optional)
            heartbeat_interval: Seconds between heartbeats
            use_sandbox: Whether to use secure sandbox (default True)
            sandbox_config: Sandbox configuration (optional)
            device_name: Name of this device (for Hub registration)
            allow_unsafe_exec: Allow direct execution outside sandbox
            custom_system_prompt: Custom system prompt template. Must
                contain ``{skill_descriptions}`` placeholder. If None
                or empty, DEFAULT_SYSTEM_PROMPT_TEMPLATE is used.
        """
        self.skills_path = Path(skills_path)
        self.hub_client = hub_client
        self.heartbeat_interval = heartbeat_interval
        self.use_sandbox = use_sandbox
        self.device_name = device_name or "local"
        if allow_unsafe_exec is None:
            allow_unsafe_exec = True
        self.allow_unsafe_exec = allow_unsafe_exec
        self._custom_system_prompt = custom_system_prompt

        self._loader = SkillLoader(skills_path)
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._registered = False
        self._skills_loaded = False
        self._disabled_skills: set[str] = set()

        self._mode_override: Optional[SkillMode] = None

        self._gatekeeper: Optional[Gatekeeper] = None
        self._proxy_gen: Optional[ProxyGenerator] = None

        # Sandbox components (initialized after skills are loaded)
        self._sandbox: Optional[SandboxExecutor] = None
        self._sandbox_config = sandbox_config or SandboxConfig(enabled=use_sandbox)

    def load_skills(self) -> List[SkillInfo]:
        """Load all skills from the skills directory.

        Returns:
            List of loaded skills
        """
        skills = self._loader.load_all()
        self._skills_loaded = True
        logger.info(f"Loaded {len(skills)} skills from {self.skills_path}")

        # Initialize sandbox components
        if self.use_sandbox:
            self._gatekeeper = Gatekeeper(self._loader)
            self._proxy_gen = ProxyGenerator(skills)
            self._sandbox = SandboxExecutor(
                gatekeeper=self._gatekeeper,
                proxy_generator=self._proxy_gen,
                config=self._sandbox_config,
            )
            logger.info("Sandbox executor initialized")

        self._configure_runtime_mode()

        return skills

    async def load_skills_async(self) -> List[SkillInfo]:
        """Load all skills asynchronously.

        Returns:
            List of all loaded skills
        """
        # For now, just delegate to sync loading
        return self.load_skills()

    def get_all_skills(self, *, include_disabled: bool = False) -> List[SkillInfo]:
        """Get all loaded skills.

        Args:
            include_disabled: If True, include disabled skills too.

        Returns:
            List of SkillInfo objects.
        """
        self._ensure_skills_loaded()
        all_skills = self._loader.get_all_skills()
        if include_disabled:
            return all_skills
        return [s for s in all_skills if s.name not in self._disabled_skills]

    def get_skill_summaries(self) -> List[Dict[str, Any]]:
        """Get plain-dict summaries of all loaded skills.

        Returns dicts with keys: name, method_count, enabled, source,
        methods, healthy, health_message.  If a skill class defines a
        ``_health_check()`` method it is called to populate the health
        fields; otherwise the skill is assumed healthy.

        Suitable for passing to the GUI without coupling.
        """
        self._ensure_skills_loaded()
        summaries = []
        for skill in self._loader.get_all_skills():
            health = self._run_health_check(skill)
            summaries.append({
                "name": skill.name,
                "method_count": len(skill.methods),
                "enabled": skill.name not in self._disabled_skills,
                "source": str(skill.module_path) if skill.module_path else "unknown",
                "methods": [
                    {"name": m.name, "signature": m.signature, "docstring": m.docstring}
                    for m in skill.methods
                ],
                "healthy": health.get("healthy", True),
                "health_message": health.get("message", ""),
            })
        return summaries

    @staticmethod
    def _run_health_check(skill: SkillInfo) -> Dict[str, Any]:
        """Run a skill's ``_health_check`` if it defines one.

        Returns:
            Dict with at least ``healthy`` (bool).  Falls back to
            ``{"healthy": True}`` when no check is defined or if the
            check itself raises an exception.
        """
        if skill.instance is None:
            msg = "Skill failed to instantiate"
            logger.warning("Health check failed for %s: %s", skill.name, msg)
            return {"healthy": False, "message": msg}
        checker = getattr(skill.instance, "_health_check", None)
        if not callable(checker):
            return {"healthy": True}
        try:
            result = checker() or {"healthy": True}
            if not result.get("healthy", True):
                logger.warning(
                    "Health check failed for %s: %s",
                    skill.name,
                    result.get("message", "unknown issue"),
                )
            return result
        except Exception as exc:
            logger.warning("Health check for %s raised: %s", skill.name, exc)
            return {"healthy": False, "message": f"Health check error: {exc}"}

    def get_load_failures(self) -> List[Dict[str, str]]:
        """Get plain-dict list of skills that failed to load.

        Returns dicts with keys: source, error.
        """
        return [{"source": f.source, "error": f.error} for f in self._loader.failures]

    def disable_skill(self, name: str) -> bool:
        """Disable a skill (excluded from prompt and execution).

        Args:
            name: Skill class name.

        Returns:
            True if the skill was found and disabled.
        """
        skill = self._loader.get_skill(name)
        if not skill:
            return False
        self._disabled_skills.add(name)
        logger.info("Disabled skill: %s", name)
        return True

    def enable_skill(self, name: str) -> bool:
        """Re-enable a previously disabled skill.

        Args:
            name: Skill class name.

        Returns:
            True if the skill was found and re-enabled.
        """
        skill = self._loader.get_skill(name)
        if not skill:
            return False
        self._disabled_skills.discard(name)
        logger.info("Enabled skill: %s", name)
        return True

    def is_skill_enabled(self, name: str) -> bool:
        """Check if a skill is enabled."""
        return name not in self._disabled_skills

    def _ensure_skills_loaded(self) -> None:
        """Ensure skills are loaded before access.

        Keeps repeated guard checks centralized.
        """
        if not self._skills_loaded:
            self.load_skills()

    def _build_device_manager(self) -> Optional[Any]:
        """Build a device manager for remote skill execution.

        Returns:
            DeviceManager instance when Hub is configured, otherwise None.
        """
        if not self.hub_client:
            return None

        from .remote import DeviceManager

        return DeviceManager(
            local_loader=self._loader,
            hub_client=self.hub_client,
            local_device_name=normalize_device_name(self.device_name),
        )

    def _build_tool_call_info(
        self, code: str, result: SkillCallResult
    ) -> Dict[str, Any]:
        """Build tool call metadata from a skill execution result.

        Args:
            code: Executed code block.
            result: Skill execution result.

        Returns:
            Tool call metadata dictionary.
        """
        return {
            "code": code,
            "success": result.success,
            "result": result.result,
            "error": result.error,
        }

    def _finalize_response(self, response: str, results: List[str]) -> str:
        """Strip tool code blocks and append tool outputs.

        Args:
            response: Original LLM response.
            results: Tool execution output lines.

        Returns:
            Cleaned response with appended results.
        """
        fence_pattern = r"```(?:python|tool_code|code|py)?\s*.*?```"
        clean_response = re.sub(
            fence_pattern,
            "",
            response,
            flags=re.DOTALL | re.IGNORECASE,
        ).strip()

        if results:
            clean_response = clean_response + "\n\n" + "\n".join(results)

        return clean_response

    async def register_with_hub(self) -> bool:
        """Register loaded skills with the Hub.

        Returns:
            True if registration succeeded
        """
        if not self.hub_client:
            logger.warning("No Hub client - skipping skill registration")
            return False

        self._ensure_skills_loaded()

        skills_data = self._loader.get_registration_data()

        if not skills_data:
            logger.info("No skills to register")
            return True

        # Register skills
        success = await self.hub_client.register_skills(skills_data)
        self._registered = True
        logger.info(f"Registered {len(skills_data)} skill methods with Hub")
        return success

    async def start_heartbeat(self):
        """Start the heartbeat task."""
        if self._heartbeat_task is not None:
            return

        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info(f"Started skill heartbeat (interval: {self.heartbeat_interval}s)")

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

    def get_system_prompt(self, *, mode_notice: Optional[str] = None) -> str:
        """Generate the system prompt with skill descriptions.

        Returns:
            System prompt string for LLM
        """
        self._ensure_skills_loaded()

        # Get all loaded skills
        skills = self.get_all_skills()

        if not skills:
            return "You are Strawberry, a helpful AI assistant."

        mode = self._get_effective_mode()

        mode_lines: list[str] = []
        if mode_notice:
            mode_lines.append(mode_notice.strip())
            mode_lines.append("")

        if mode == SkillMode.LOCAL:
            mode_lines.extend(
                [
                    "Runtime mode: OFFLINE/LOCAL.",
                    "- Use only the local device proxy: device.<SkillName>.<method>(...) ",
                    "- Do NOT use devices.* or device_manager.* (they are unavailable).",
                ]
            )
        else:
            mode_lines.extend(
                [
                    "Runtime mode: ONLINE (Hub).",
                    "- Use the remote devices proxy: devices.<Device>.<SkillName>.<method>(...) ",
                    "- You may also use device_manager.* as a legacy alias.",
                ]
            )

        mode_preamble = "\n".join(mode_lines).strip()

        # Build skill descriptions
        descriptions = []
        for skill in skills:
            descriptions.append(f"### {skill.name}")
            if skill.class_obj.__doc__:
                descriptions.append(skill.class_obj.__doc__.strip())
            descriptions.append("")

            for method in skill.methods:
                prefix = "device"
                if mode == SkillMode.REMOTE:
                    prefix = "devices.{device_name}".format(
                        device_name=normalize_device_name(self.device_name)
                    )
                descriptions.append(f"- `{prefix}.{skill.name}.{method.signature}`")
                if method.docstring:
                    # Just first line of docstring
                    first_line = method.docstring.split('\n')[0].strip()
                    descriptions.append(f"  {first_line}")
            descriptions.append("")

        skill_text = "\n".join(descriptions)

        # Use custom system prompt template if set, otherwise default.
        template = self._custom_system_prompt or self.DEFAULT_SYSTEM_PROMPT_TEMPLATE
        try:
            prompt = template.format(skill_descriptions=skill_text)
        except KeyError:
            # User template is missing {skill_descriptions} — append skills.
            logger.warning(
                "Custom system prompt missing {skill_descriptions} placeholder; "
                "appending skill list."
            )
            prompt = template + "\n\n## Available Skills\n\n" + skill_text

        if mode_preamble:
            return f"{mode_preamble}\n\n{prompt}"
        return prompt

    def set_custom_system_prompt(self, prompt: Optional[str]) -> None:
        """Update the custom system prompt template at runtime.

        Args:
            prompt: New template string (should contain
                ``{skill_descriptions}``), or None to revert to default.
        """
        self._custom_system_prompt = prompt or None

    def parse_skill_calls(self, response: str) -> List[str]:
        """Parse skill calls from LLM response.

        Extracts Python code blocks that may contain skill calls.
        Also detects "bare" code lines that look like skill calls.

        Args:
            response: LLM response text

        Returns:
            List of code blocks to execute
        """
        code_blocks = []

        # 1. Match fenced code blocks: ```python, ```tool_code, ```code, etc.
        # LLMs use various fence names - accept common ones
        fenced_pattern = r'```(?:python|tool_code|code|py)?\s*(.*?)\s*```'
        fenced_matches = re.findall(fenced_pattern, response, re.DOTALL | re.IGNORECASE)
        code_blocks.extend([m.strip() for m in fenced_matches if m.strip()])

        # 2. If no fenced blocks found, look for bare device.* calls
        if not code_blocks:
            mode = self._get_effective_mode()
            allowed_roots = ("device",)
            if mode == SkillMode.REMOTE:
                allowed_roots = ("device", "devices", "device_manager")

            # Match lines that look like: print(device.Something...) or device.Something...
            bare_pattern = (
                r"^[\s]*((?:print\s*\()?\s*(?:"
                + "|".join(allowed_roots)
                + r")\."
                r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\s*\([^)]*\)\s*\)?)"
            )
            for line in response.split('\n'):
                match = re.match(bare_pattern, line.strip())
                if match:
                    code = match.group(1).strip()
                    # Ensure print() wrapper for output
                    if not code.startswith('print('):
                        code = f'print({code})'
                    code_blocks.append(code)

        return code_blocks

    async def execute_code_async(self, code: str) -> SkillCallResult:
        """Execute a code block containing skill calls (async, sandbox).

        Args:
            code: Python code to execute

        Returns:
            SkillCallResult with output or error
        """
        if self._sandbox:
            result = await self._sandbox.execute(code)
            # IMPORTANT: Sandbox fallback strategy when Deno is not installed
            #
            # The sandbox (Deno + Pyodide) is the secure execution environment, but it's
            # not always available (e.g., Deno not installed, development mode).
            #
            # SAFE to fall back to direct exec:
            # - Local device skills (device.* or devices.<this_device>.*)
            # - These run in the same process/event loop, no cross-thread issues
            #
            # Remote device calls are supported in the fallback path via *sync HTTP*
            # methods on HubClient (see HubClient.search_skills_sync and
            # HubClient.execute_remote_skill_sync). This avoids event-loop coupling.
            if not result.success and "Deno not installed" in (result.error or ""):
                logger.warning(
                    "Sandbox unavailable (Deno not installed), falling back to direct "
                    "execution"
                )
                if not self.allow_unsafe_exec:
                    return SkillCallResult(
                        success=False,
                        error=(
                            "Sandbox unavailable and unsafe execution is disabled. "
                            "Enable skills.allow_unsafe_exec to allow fallback."
                        ),
                    )
                return self.execute_code(code)
            return SkillCallResult(
                success=result.success,
                result=result.output,
                error=result.error,
            )
        else:
            # Fallback to sync execution if sandbox not initialized
            return self.execute_code(code)

    def execute_code(self, code: str) -> SkillCallResult:
        """Execute a code block containing skill calls (sync, thread-safe).

        Uses RestrictedPython to compile and execute user code in a secure,
        isolated environment. Output is captured via a per-execution print
        function, not global sys.stdout manipulation.

        Args:
            code: Python code to execute

        Returns:
            SkillCallResult with output or error
        """
        from .restricted_executor import execute_restricted

        if not self.allow_unsafe_exec and self.use_sandbox:
            return SkillCallResult(
                success=False,
                error=(
                    "Direct execution is disabled while sandbox mode is enabled. "
                    "Use execute_code_async() or enable skills.allow_unsafe_exec."
                ),
            )

        forbidden_names = {"__import__", "open", "eval", "exec", "compile", "input"}
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return SkillCallResult(success=False, error=f"SyntaxError: {exc}")
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                return SkillCallResult(
                    success=False,
                    error="Import statements are not allowed in skill execution.",
                )
            if isinstance(node, ast.Name) and node.id in forbidden_names:
                return SkillCallResult(
                    success=False,
                    error=f"Unsafe built-in '{node.id}' is not allowed.",
                )

        mode = self._get_effective_mode()

        # Enforce mode correctness: in OFFLINE/LOCAL mode there is no Hub client, so
        # devices.* and device_manager.* must not be used.
        if mode == SkillMode.LOCAL and ("devices." in code or "device_manager." in code):
            return SkillCallResult(
                success=False,
                error=(
                    "Remote devices proxy is unavailable in OFFLINE/LOCAL mode. "
                    "Use device.<SkillName>.<method>(...) instead of devices.*"
                ),
            )

        # Create device proxy for local skills
        device = _DeviceProxy(self._loader)

        # Prepare device manager for remote calls (if Hub is connected)
        device_manager = self._build_device_manager()

        # Execute with RestrictedPython
        result = execute_restricted(
            code=code,
            device_proxy=device,
            device_manager=device_manager,
        )

        return SkillCallResult(
            success=result.success,
            result=result.output if result.success else None,
            error=result.error,
        )

    def _is_remote_device_call(self, code: str) -> bool:
        """Check if code calls a remote device (not the local device).

        Returns True if code references devices.<other_device>.* or device_manager.*
        Returns False if code only uses device.* or devices.<this_device>.*
        """
        # device_manager.* is always remote (cross-device discovery)
        if "device_manager." in code:
            return True

        # device.* is always local
        if "devices." not in code:
            return False

        # Check if it's devices.<local_device_name>.* (which is actually local)
        local_device_name = normalize_device_name(self.device_name)
        local_pattern = f"devices.{local_device_name}."

        # Simple heuristic: if code contains devices. but NOT our local device name,
        # it's a remote call
        if local_pattern in code:
            # Contains local device reference - check if there are OTHER device references
            # For now, conservatively allow if local device is referenced
            # (A more sophisticated check would parse the AST to find all device references)
            return False

        # Contains devices. but not our local device - must be remote
        return True

    async def process_response_async(self, response: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Process LLM response, executing any skill calls (async, sandbox).

        Args:
            response: LLM response text

        Returns:
            Tuple of (final_response, list of tool_call_info)
        """
        code_blocks = self.parse_skill_calls(response)

        if not code_blocks:
            return response, []

        tool_calls = []
        results = []

        for code in code_blocks:
            result = await self.execute_code_async(code)

            tool_calls.append(self._build_tool_call_info(code, result))

            if result.success and result.result:
                results.append(f"Output:\n{result.result}")
            elif not result.success:
                results.append(f"Error: {result.error}")

        clean_response = self._finalize_response(response, results)
        return clean_response, tool_calls

    def process_response(self, response: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Process LLM response, executing any skill calls (sync).

        WARNING: Uses direct exec() - not secure for production.
        Use process_response_async() for secure sandbox execution.

        Args:
            response: LLM response text

        Returns:
            Tuple of (final_response, list of tool_call_info)
        """
        code_blocks = self.parse_skill_calls(response)

        if not code_blocks:
            return response, []

        tool_calls = []
        results = []

        for code in code_blocks:
            result = self.execute_code(code)

            tool_calls.append(self._build_tool_call_info(code, result))

            if result.success and result.result:
                results.append(f"Output:\n{result.result}")
            elif not result.success:
                results.append(f"Error: {result.error}")

        clean_response = self._finalize_response(response, results)
        return clean_response, tool_calls

    def get_skill(self, name: str) -> Optional[SkillInfo]:
        """Get a skill by class name."""
        return self._loader.get_skill(name)

    async def shutdown(self):
        """Shutdown the skill service and sandbox."""
        await self.stop_heartbeat()

        if self._sandbox:
            await self._sandbox.shutdown()
            self._sandbox = None
            logger.info("Sandbox shutdown complete")

    def reload_skills(self) -> List[SkillInfo]:
        """Reload all skills and refresh sandbox.

        Returns:
            List of reloaded skills
        """
        skills = self._loader.load_all()
        self._skills_loaded = True

        # Refresh sandbox components
        if self._sandbox:
            self._sandbox.refresh_skills()

        logger.info(f"Reloaded {len(skills)} skills")
        return skills

    async def execute_skill_by_name(
        self,
        skill_name: str,
        method_name: str,
        args: list,
        kwargs: dict,
    ) -> Any:
        """Execute a skill method by name (for WebSocket requests).

        Args:
            skill_name: Skill class name
            method_name: Method name to call
            args: Positional arguments
            kwargs: Keyword arguments

        Returns:
            Result from skill execution

        Raises:
            ValueError: If skill or method not found
            RuntimeError: If skill execution fails
        """
        self._ensure_skills_loaded()

        # Get skill
        skill = self._loader.get_skill(skill_name)
        if not skill:
            raise ValueError(f"Skill '{skill_name}' not found")

        # Call method
        try:
            result = self._loader.call_method(skill_name, method_name, *args, **kwargs)
            logger.info(f"Executed {skill_name}.{method_name} -> {result}")
            return result
        except Exception as e:
            msg = str(e).strip() if str(e).strip() else f"{type(e).__name__} (no details)"
            logger.error(f"Skill execution failed: {skill_name}.{method_name} - {msg}")
            raise RuntimeError(
                f"{skill_name}.{method_name} failed: {msg}"
            ) from e

    # =========================================================================
    # TensorZero Tool Call Execution
    # =========================================================================

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a TensorZero tool call.

        Args:
            tool_name: Name of the tool (search_skills, describe_function, python_exec)
            arguments: Tool arguments

        Returns:
            Dict with "result" or "error" key
        """
        try:
            if tool_name == "search_skills":
                query = arguments.get("query", "")
                device_limit = int(arguments.get("device_limit", 10) or 10)
                result = self._execute_search_skills(query, device_limit=device_limit)
                return {"result": result}

            elif tool_name == "describe_function":
                path = arguments.get("path", "")
                result = self._execute_describe_function(path)
                return {"result": result}

            elif tool_name == "python_exec":
                code = arguments.get("code", "")
                code = self._prepare_python_exec_code(code)
                result = self.execute_code(code)
                if result.success:
                    return {"result": result.result or "(no output)"}
                else:
                    return {"error": _enrich_exec_error(result.error or "")}

            else:
                return {"error": f"Unknown tool: {tool_name}"}

        except Exception as e:
            import traceback
            return {"error": f"{type(e).__name__}: {e}\n{traceback.format_exc()}"}

    def _prepare_python_exec_code(self, code: str) -> str:
        """Rewrite python_exec code to behave more like a notebook cell.

        If the last top-level statement is a bare expression (for example:
        `devices.new.InternetSearchSkill.search_web_detailed("bacon")`), rewrite
        the code to evaluate the expression and print its str(). This ensures
        `python_exec` returns useful output even when the user/model forgets to
        wrap the expression in `print(...)`.

        Args:
            code: Original Python code.

        Returns:
            Rewritten Python code (or original code if not applicable).
        """
        if not code or not code.strip():
            return code

        try:
            module = ast.parse(code)
        except SyntaxError:
            return code

        if not module.body:
            return code

        last_stmt = module.body[-1]
        if not isinstance(last_stmt, ast.Expr):
            return code

        expr_value = last_stmt.value
        if isinstance(expr_value, ast.Call) and isinstance(expr_value.func, ast.Name):
            if expr_value.func.id == "print":
                return code

        # RestrictedPython rejects assignment to names starting with an underscore.
        # Use an unprefixed temp name for compatibility.
        last_name = "strawberry_last"

        assign = ast.Assign(
            targets=[ast.Name(id=last_name, ctx=ast.Store())],
            value=expr_value,
        )
        # Use str() instead of repr() for the auto-print so the LLM sees
        # clean output (e.g. "Hello" not "'Hello'", and readable dicts
        # instead of Python repr formatting).
        print_call = ast.Expr(
            value=ast.Call(
                func=ast.Name(id="print", ctx=ast.Load()),
                args=[
                    ast.Call(
                        func=ast.Name(id="str", ctx=ast.Load()),
                        args=[ast.Name(id=last_name, ctx=ast.Load())],
                        keywords=[],
                    )
                ],
                keywords=[],
            )
        )

        module.body = [*module.body[:-1], assign, print_call]
        ast.fix_missing_locations(module)

        try:
            return ast.unparse(module)
        except Exception:
            return code

    def set_hub_client(self, hub_client: Optional[HubClient]) -> None:
        """Update the Hub client and reconfigure runtime mode.

        Args:
            hub_client: New Hub client instance or None.
        """
        self.hub_client = hub_client
        self._configure_runtime_mode()

    def set_mode_override(self, mode: Optional[SkillMode]) -> None:
        """Override the runtime mode for skill execution.

        Args:
            mode: Forced skill mode, or None to use automatic selection.
        """
        self._mode_override = mode
        self._configure_runtime_mode()

    def _get_effective_mode(self) -> SkillMode:
        """Resolve the current skill runtime mode.

        Returns:
            SkillMode.LOCAL if Hub is unavailable, otherwise SkillMode.REMOTE.
        """
        if self._mode_override is not None:
            # Never report REMOTE if no Hub client is configured.
            if self._mode_override == SkillMode.REMOTE and not self.hub_client:
                return SkillMode.LOCAL
            return self._mode_override
        return SkillMode.REMOTE if self.hub_client else SkillMode.LOCAL

    def _configure_runtime_mode(self) -> None:
        """Configure sandbox proxies for the current runtime mode."""
        if not self.use_sandbox:
            return
        if not self._sandbox or not self._gatekeeper or not self._proxy_gen:
            return

        mode = self._get_effective_mode()

        if mode == SkillMode.REMOTE:
            self._gatekeeper.set_device_manager(
                self._build_device_manager()
            )
            self._proxy_gen.set_mode(SkillMode.REMOTE)
        else:
            self._gatekeeper.device_manager = None
            self._proxy_gen.set_mode(SkillMode.LOCAL)

    async def execute_tool_async(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a TensorZero tool call (async version for sandbox).

        Args:
            tool_name: Name of the tool (search_skills, describe_function, python_exec)
            arguments: Tool arguments

        Returns:
            Dict with "result" or "error" key
        """
        try:
            mode = self._get_effective_mode()
            if tool_name == "search_skills":
                return await self._tool_search_skills(arguments, mode)
            elif tool_name == "describe_function":
                return await self._tool_describe_function(arguments, mode)
            elif tool_name == "python_exec":
                return await self._tool_python_exec(arguments)
            else:
                return {
                    "error": (
                        f"Unknown tool: {tool_name}. "
                        "Use one of the available tools: search_skills, "
                        "describe_function, python_exec. "
                        "To call a skill method like multiply, use python_exec with code like: "
                        "print(device.CalculatorSkill.multiply(a=5, b=3))"
                    )
                }

        except Exception as e:
            import traceback
            return {"error": f"{type(e).__name__}: {e}\n{traceback.format_exc()}"}

    async def _tool_search_skills(
        self, arguments: Dict[str, Any], mode: "SkillMode",
    ) -> Dict[str, Any]:
        """Handle the search_skills tool call."""
        query = arguments.get("query", "")
        device_limit = int(arguments.get("device_limit", 10) or 10)
        if mode == SkillMode.REMOTE and self.hub_client:
            results = await self.hub_client.search_skills(
                query=query,
                device_limit=device_limit,
            )
            return {"result": self._format_search_results(results)}

        result = self._execute_search_skills(query, device_limit=device_limit)
        return {"result": result}

    async def _tool_describe_function(
        self, arguments: Dict[str, Any], mode: "SkillMode",
    ) -> Dict[str, Any]:
        """Handle the describe_function tool call."""
        path = arguments.get("path", "")
        if mode == SkillMode.REMOTE and self.hub_client:
            return await self._describe_function_remote(path)

        result = self._execute_describe_function(path)
        return {"result": result}

    async def _describe_function_remote(self, path: str) -> Dict[str, Any]:
        """Describe a function via the Hub (remote mode)."""
        query = path.split(".")[0] if path else ""
        results = await self.hub_client.search_skills(
            query=query, device_limit=10,
        )

        for skill in results:
            if skill.get("path") == path:
                signature = skill.get("signature", "")
                doc = skill.get("docstring", "") or skill.get("summary", "")
                devices = skill.get("devices", [])
                device_count = int(skill.get("device_count", 0) or 0)

                devices_info = ""
                if devices:
                    devices_info = "\n\n# Available on: " + ", ".join(devices[:5])
                    if device_count > 5:
                        devices_info += f" (+{device_count - 5} more)"

                return {
                    "result": (
                        f'def {signature}:\n    """{doc}"""'
                        + devices_info
                    )
                }

        return {"error": f"Function not found: {path}"}

    async def _tool_python_exec(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle the python_exec tool call."""
        code = arguments.get("code", "")
        code = self._prepare_python_exec_code(code)
        result = await self.execute_code_async(code)
        if result.success:
            return {"result": result.result or "(no output)"}
        else:
            return {"error": _enrich_exec_error(result.error or "")}

    @staticmethod
    def _format_search_results(results: List[Dict[str, Any]]) -> str:
        """Format search results as a compact text table for the LLM.

        Produces one line per result instead of verbose JSON, saving tokens
        and making it easier for the LLM to scan for the right skill.

        Args:
            results: List of dicts with path, signature, summary keys.

        Returns:
            Human/LLM-readable text listing.
        """
        if not results:
            return "No results found."

        lines = [f"Found {len(results)} result(s):"]
        for r in results:
            sig = r.get("signature", r.get("path", "?"))
            summary = r.get("summary", "")
            path = r.get("path", "")
            # Include device info if present (online/Hub results)
            devices = r.get("devices", [])
            device_suffix = ""
            if devices:
                device_suffix = f"  [on: {', '.join(devices[:3])}]"
            line = f"  {path} — {sig}"
            if summary:
                line += f" — {summary}"
            line += device_suffix
            lines.append(line)
        return "\n".join(lines)

    def _execute_search_skills(self, query: str, device_limit: int = 10) -> str:
        """Execute search_skills tool.

        Args:
            query: Search query
            device_limit: Number of sample devices to return per skill (online mode)

        Returns:
            Compact text listing of search results.
        """
        self._ensure_skills_loaded()

        # Use device proxy for search (has the search_skills method)
        device = _DeviceProxy(self._loader)
        results = device.search_skills(query, device_limit=device_limit)

        return self._format_search_results(results)

    def _execute_describe_function(self, path: str) -> str:
        """Execute describe_function tool.

        Args:
            path: Function path (SkillName.method_name)

        Returns:
            Function description string
        """
        self._ensure_skills_loaded()

        device = _DeviceProxy(self._loader)
        return device.describe_function(path)


# Common English stop words to strip from search queries.
# Prevents "turn on the lamp" from matching everything via "the" or "on".
_SEARCH_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "to", "for", "of", "in", "on", "it",
    "and", "or", "my", "me", "i", "do", "can", "you", "please",
    "what", "how", "get", "set",
})

# Hints appended to common python_exec errors so the LLM can self-correct.
_ERROR_HINTS: Dict[str, str] = {
    "import": (
        "\nHint: Imports are not allowed in python_exec. "
        "All skill methods are available via device.<SkillName>.<method>()."
    ),
    "__import__": (
        "\nHint: Imports are not allowed in python_exec. "
        "All skill methods are available via device.<SkillName>.<method>()."
    ),
    "open": (
        "\nHint: File I/O is not allowed in python_exec."
    ),
    "not found": (
        "\nHint: Use search_skills to find available skills, "
        "then describe_function to see the full signature."
    ),
    "not allowed": (
        "\nHint: This operation is restricted for security. "
        "Use device.<SkillName>.<method>() to call skills."
    ),
}


def _enrich_exec_error(error: str) -> str:
    """Append an actionable hint to a python_exec error message.

    Scans the error text for known patterns and appends a short hint
    so the LLM can self-correct without extra round-trips.

    Args:
        error: Raw error message string.

    Returns:
        Error string, possibly with an appended hint.
    """
    if not error:
        return error
    error_lower = error.lower()
    for pattern, hint in _ERROR_HINTS.items():
        if pattern in error_lower:
            return error + hint
    return error


def _build_example_call(skill_name: str, method: SkillMethod) -> str:
    """Build a ready-to-use python_exec example for a skill method.

    Parses the method signature to generate placeholder arguments so the
    LLM can copy-paste and fill in real values.

    Args:
        skill_name: Name of the skill class.
        method: SkillMethod with signature info.

    Returns:
        Example code string, e.g.
        ``print(device.CalcSkill.add(a=5, b=3))``
    """
    sig = method.signature  # e.g. "add(a: int, b: int) -> int"
    # Extract the params portion between parens
    match = re.search(r"\(([^)]*)\)", sig)
    if not match:
        return f"print(device.{skill_name}.{method.name}())"

    params_str = match.group(1).strip()
    if not params_str:
        return f"print(device.{skill_name}.{method.name}())"

    # Parse individual params
    example_args: list[str] = []
    for param in params_str.split(","):
        param = param.strip()
        if not param:
            continue
        # Skip **kwargs params and the bare '*' keyword-only separator
        if param.startswith("**") or param == "*":
            continue

        # Extract name and optional default
        # Formats: "name: type", "name: type = default", "name=default"
        name = param.split(":")[0].split("=")[0].strip()

        # Check for a default value
        if "=" in param:
            default = param.rsplit("=", 1)[1].strip()
            # None defaults are unhelpful for the LLM — use a type placeholder
            if default == "None":
                type_hint = ""
                if ":" in param:
                    type_hint = param.split(":", 1)[1].split("=")[0].strip().lower()
                default = _placeholder_for_type(type_hint)
            example_args.append(f"{name}={default}")
        else:
            # Generate a placeholder based on type hint
            type_hint = ""
            if ":" in param:
                type_hint = param.split(":", 1)[1].split("=")[0].strip().lower()

            placeholder = _placeholder_for_type(type_hint)
            example_args.append(f"{name}={placeholder}")

    args_str = ", ".join(example_args)
    return f"print(device.{skill_name}.{method.name}({args_str}))"


def _placeholder_for_type(type_hint: str) -> str:
    """Return a sensible placeholder value for a type hint.

    Args:
        type_hint: Lowercase type hint string.

    Returns:
        Placeholder value as a string.
    """
    if not type_hint:
        return "..."
    if "str" in type_hint:
        return "'...'"
    if "int" in type_hint:
        return "0"
    if "float" in type_hint:
        return "0.0"
    if "bool" in type_hint:
        return "True"
    if "list" in type_hint:
        return "[]"
    if "dict" in type_hint:
        return "{}"
    return "..."


class _DeviceProxy:
    """Proxy object for accessing skills from LLM-generated code.

    Provides:
    - device.search_skills("query") - Find skills by keyword
    - device.describe_function("SkillName.method") - Get function details
    - device.SkillName.method_name(args) - Call a skill
    """

    def __init__(self, loader: SkillLoader):
        """Initialize the device proxy.

        Args:
            loader: Skill loader used to resolve skills.
        """
        self._loader = loader

    def search_skills(self, query: str = "", device_limit: int = 10) -> List[Dict[str, Any]]:
        """Search for skills by keyword.

        Splits the query into words and matches if **any** word appears
        in the method name, skill name, signature, or docstring.  This
        makes multi-word queries like "react documentation" find results
        that match on "documentation" alone.

        Args:
            query: Search term (matches name, signature, docstring)
            device_limit: Ignored for local-only mode

        Returns:
            List of matching skills with path, signature, summary
        """
        query_words = self._parse_query_words(query)
        candidates = self._build_search_candidates(query_words)
        matched = self._match_candidates(candidates, query_words)

        results = []
        for skill, method in matched:
            summary = ""
            if method.docstring:
                summary = method.docstring.split("\n")[0].strip()
            results.append({
                "path": f"{skill.name}.{method.name}",
                "signature": method.signature,
                "summary": summary,
            })
        return results

    @staticmethod
    def _parse_query_words(query: str) -> list[str]:
        """Parse a query into search words, stripping stop words."""
        raw_words = query.lower().split() if query else []
        query_words = [w for w in raw_words if w not in _SEARCH_STOP_WORDS]
        # Fall back to original words if stop-word stripping removed everything
        if not query_words and raw_words:
            query_words = raw_words
        return query_words

    def _build_search_candidates(
        self, query_words: list[str],
    ) -> list[tuple]:
        """Build (skill, method, searchable_text) triples."""
        candidates: list[tuple] = []
        for skill in self._loader.get_all_skills():
            for method in skill.methods:
                if not query_words:
                    candidates.append((skill, method, True))
                else:
                    searchable = (
                        f"{method.name} {skill.name} "
                        f"{method.signature} "
                        f"{method.docstring or ''}"
                    ).lower()
                    candidates.append((skill, method, searchable))
        return candidates

    @staticmethod
    def _match_candidates(
        candidates: list[tuple], query_words: list[str],
    ) -> list[tuple]:
        """Match candidates against query words (all-words first, then any-word)."""
        if not query_words:
            return [(s, m) for s, m, _ in candidates]

        matched = [
            (s, m) for s, m, txt in candidates
            if txt is True or all(w in txt for w in query_words)
        ]
        if not matched:
            matched = [
                (s, m) for s, m, txt in candidates
                if txt is True or any(w in txt for w in query_words)
            ]
        return matched

    def describe_function(self, path: str) -> str:
        """Get full function details including docstring.

        Args:
            path: "SkillName.method_name"

        Returns:
            Full function signature with docstring
        """
        parts = path.split(".")
        if len(parts) != 2:
            return f"Error: Invalid path '{path}'. Use format 'SkillName.method_name'"

        skill_name, method_name = parts
        skill = self._loader.get_skill(skill_name)

        if not skill:
            return f"Error: Skill '{skill_name}' not found"

        for method in skill.methods:
            if method.name == method_name:
                doc = method.docstring or "No description available"
                example = _build_example_call(skill_name, method)
                result = f"def {method.signature}:\n    \"\"\"\n    {doc}\n    \"\"\""
                if example:
                    result += f'\n\nExample:\n  python_exec(code="{example}")'
                return result

        return f"Error: Method '{method_name}' not found in {skill_name}"

    def __getattr__(self, name: str):
        """Get a skill class by name for direct calls."""
        # Don't intercept private attributes
        if name.startswith("_"):
            raise AttributeError(name)

        skill = self._loader.get_skill(name)
        if skill is None:
            # Get list of available skills for helpful error
            available = [s.name for s in self._loader.get_all_skills()]
            available_str = ", ".join(available) if available else "none loaded"
            raise AttributeError(
                f"Skill '{name}' not found. "
                f"Available skills: {available_str}. "
                f"Use device.search_skills() to search."
            )
        return _SkillProxy(self._loader, name)


class _SkillProxy:
    """Proxy for a specific skill class."""

    def __init__(self, loader: SkillLoader, skill_name: str):
        """Initialize a proxy for a single skill.

        Args:
            loader: Skill loader used to resolve methods.
            skill_name: Skill class name.
        """
        self._loader = loader
        self._skill_name = skill_name

    def __getattr__(self, name: str):
        """Get a method that calls the actual skill."""
        def method_wrapper(*args, **kwargs):
            return self._loader.call_method(self._skill_name, name, *args, **kwargs)
        return method_wrapper


class _DeviceManagerProxy:
    """Proxy object for accessing skills across multiple devices (online mode).

    Provides:
    - device_manager.search_skills("query") - Find skills across all devices
    - device_manager.describe_function("device.SkillName.method") - Get function details
    - device_manager.device_name.SkillName.method(args) - Call skill on specific device

    Uses __getattr__ for dynamic device access so devices can connect/disconnect
    during a chat session.
    """

    def __init__(
        self,
        local_loader: SkillLoader,
        hub_client: Optional[HubClient] = None,
        connected_devices: Optional[Dict[str, Dict[str, Any]]] = None,
        local_device_name: Optional[str] = None,
    ):
        """Initialize device manager proxy.

        Args:
            local_loader: Local skill loader for this device
            hub_client: Hub client for remote skill calls
            connected_devices: Dict mapping device_name -> device_info with skills
            local_device_name: Name of the local device (will be normalized)
        """
        self._local_loader = local_loader
        self._hub_client = hub_client
        self._connected_devices: Dict[str, Dict[str, Any]] = connected_devices or {}
        self._local_device_name = (
            normalize_device_name(local_device_name) if local_device_name else "local"
        )

    def set_local_device_name(self, name: str) -> None:
        """Set the name of the local device."""
        self._local_device_name = normalize_device_name(name)

    def update_connected_devices(self, devices: Dict[str, Dict[str, Any]]) -> None:
        """Update the list of connected devices and their skills.

        Args:
            devices: Dict mapping device_name -> {"skills": [...], "online": bool}
        """
        self._connected_devices = {
            normalize_device_name(k): v for k, v in devices.items()
        }

    def search_skills(self, query: str = "", device_limit: int = 10) -> List[Dict[str, Any]]:
        """Search for skills across all connected devices.

        Args:
            query: Search term (matches name, signature, docstring)

        Returns:
            List of skills with path, signature, summary, and devices list
        """
        device_limit = max(1, min(int(device_limit or 10), 100))
        skill_map: Dict[str, Dict[str, Any]] = {}

        self._add_local_skills(query, skill_map)
        self._add_remote_skills(query, skill_map, device_limit)

        return list(skill_map.values())

    def _add_local_skills(
        self, query: str, skill_map: Dict[str, Dict[str, Any]],
    ) -> None:
        """Add matching local skills to the skill map."""
        query_lower = query.lower() if query else ""
        for skill in self._local_loader.get_all_skills():
            for method in skill.methods:
                if not self._skill_matches(
                    query_lower, method.name, skill.name,
                    method.signature, method.docstring or "",
                ):
                    continue
                key = f"{skill.name}.{method.name}"
                summary = (method.docstring or "").split("\n")[0].strip()
                if key not in skill_map:
                    skill_map[key] = {
                        "path": key,
                        "signature": method.signature,
                        "summary": summary,
                        "devices": [],
                        "device_count": 0,
                    }
                if self._local_device_name not in skill_map[key]["devices"]:
                    skill_map[key]["devices"].append(self._local_device_name)
                skill_map[key]["device_count"] += 1

    def _add_remote_skills(
        self, query: str, skill_map: Dict[str, Dict[str, Any]],
        device_limit: int,
    ) -> None:
        """Add matching remote device skills to the skill map."""
        query_lower = query.lower() if query else ""
        for device_name, device_info in self._connected_devices.items():
            if not device_info.get("online", False):
                continue
            for skill_data in device_info.get("skills", []):
                skill_name = skill_data.get("class_name", "")
                method_name = skill_data.get("function_name", "")
                signature = skill_data.get("signature", "")
                docstring = skill_data.get("docstring", "")
                if not self._skill_matches(
                    query_lower, method_name, skill_name, signature, docstring,
                ):
                    continue
                key = f"{skill_name}.{method_name}"
                summary = docstring.split("\n")[0].strip() if docstring else ""
                if key not in skill_map:
                    skill_map[key] = {
                        "path": key,
                        "signature": signature,
                        "summary": summary,
                        "devices": [],
                        "device_count": 0,
                    }
                skill_map[key]["device_count"] += 1
                if (
                    device_name not in skill_map[key]["devices"]
                    and len(skill_map[key]["devices"]) < device_limit
                ):
                    skill_map[key]["devices"].append(device_name)

    @staticmethod
    def _skill_matches(
        query_lower: str, method_name: str, skill_name: str,
        signature: str, docstring: str,
    ) -> bool:
        """Return True if a skill method matches the search query."""
        if not query_lower:
            return True
        return (
            query_lower in method_name.lower()
            or query_lower in skill_name.lower()
            or query_lower in signature.lower()
            or query_lower in docstring.lower()
        )

    def describe_function(self, path: str) -> str:
        """Get full function details including docstring.

        Args:
            path: "device_name.SkillName.method_name" or "SkillName.method_name"

        Returns:
            Full function signature with docstring
        """
        parts = path.split(".")

        if len(parts) == 2:
            skill_name, method_name = parts
            return self._describe_local_method(skill_name, method_name)

        elif len(parts) == 3:
            device_name, skill_name, method_name = parts
            device_name = normalize_device_name(device_name)

            # Local device
            if device_name == self._local_device_name:
                result = self._describe_local_method(skill_name, method_name)
                if not result.startswith("Error:"):
                    return result

            # Remote devices
            device_info = self._connected_devices.get(device_name)
            if device_info:
                for skill_data in device_info.get("skills", []):
                    if (skill_data.get("class_name") == skill_name and
                            skill_data.get("function_name") == method_name):
                        sig = skill_data.get("signature", f"{method_name}()")
                        doc = skill_data.get("docstring", "No description available")
                        return f'def {sig}:\n    """\n    {doc}\n    """'

            return f"Error: Function '{path}' not found"

        return f"Error: Invalid path '{path}'. Use 'SkillName.method' or 'device.SkillName.method'"

    def _describe_local_method(self, skill_name: str, method_name: str) -> str:
        """Describe a method from the local skill loader."""
        skill = self._local_loader.get_skill(skill_name)
        if skill:
            for method in skill.methods:
                if method.name == method_name:
                    doc = method.docstring or "No description available"
                    return f'def {method.signature}:\n    """\n    {doc}\n    """'
        return f"Error: Method '{method_name}' not found in {skill_name}"

    def __getattr__(self, name: str) -> "_RemoteDeviceProxy":
        """Get a device by name for skill calls.

        Uses __getattr__ so devices can connect/disconnect during conversation.
        """
        if name.startswith("_"):
            raise AttributeError(name)

        normalized = normalize_device_name(name)

        # Check if it's the local device
        if normalized == self._local_device_name:
            return _LocalDeviceSkillsProxy(self._local_loader)

        # Check if device exists in connected devices
        if normalized not in self._connected_devices:
            available = list(self._connected_devices.keys())
            if self._local_device_name:
                available.insert(0, self._local_device_name)
            available_str = ", ".join(available) if available else "none connected"
            raise AttributeError(
                f"Device '{name}' not connected. "
                f"Available devices: {available_str}. "
                f"Use device_manager.search_skills() to see all skills."
            )

        device_info = self._connected_devices[normalized]
        if not device_info.get("online", False):
            raise AttributeError(f"Device '{name}' is currently offline.")

        return _RemoteDeviceProxy(normalized, self._hub_client)


class _LocalDeviceSkillsProxy:
    """Proxy for accessing local device skills through device_manager."""

    def __init__(self, loader: SkillLoader):
        """Initialize the local device proxy.

        Args:
            loader: Skill loader used to resolve skills.
        """
        self._loader = loader

    def __getattr__(self, skill_name: str) -> "_SkillProxy":
        """Resolve a skill class by name.

        Args:
            skill_name: Skill class name.

        Returns:
            Skill proxy for invoking methods.
        """
        if skill_name.startswith("_"):
            raise AttributeError(skill_name)
        skill = self._loader.get_skill(skill_name)
        if skill is None:
            available = [s.name for s in self._loader.get_all_skills()]
            raise AttributeError(
                f"Skill '{skill_name}' not found. Available: {', '.join(available)}"
            )
        return _SkillProxy(self._loader, skill_name)


class _RemoteDeviceProxy:
    """Proxy for accessing skills on a remote device."""

    def __init__(self, device_name: str, hub_client: Optional[HubClient]):
        """Initialize the remote device proxy.

        Args:
            device_name: Normalized device name.
            hub_client: Hub client used for remote calls.
        """
        self._device_name = device_name
        self._hub_client = hub_client

    def __getattr__(self, skill_name: str) -> "_RemoteSkillProxy":
        """Resolve a remote skill by name.

        Args:
            skill_name: Skill class name.

        Returns:
            Proxy for the remote skill.
        """
        if skill_name.startswith("_"):
            raise AttributeError(skill_name)
        return _RemoteSkillProxy(self._device_name, skill_name, self._hub_client)


class _RemoteSkillProxy:
    """Proxy for a skill on a remote device."""

    def __init__(self, device_name: str, skill_name: str, hub_client: Optional[HubClient]):
        """Initialize the remote skill proxy.

        Args:
            device_name: Target device name.
            skill_name: Skill class name.
            hub_client: Hub client used for remote calls.
        """
        self._device_name = device_name
        self._skill_name = skill_name
        self._hub_client = hub_client

    def __getattr__(self, method_name: str):
        """Get a method that calls the remote skill."""
        if method_name.startswith("_"):
            raise AttributeError(method_name)

        def method_wrapper(*args, **kwargs):
            if not self._hub_client:
                raise RuntimeError("Hub client not available for remote skill calls")

            # This will be called synchronously from sandbox
            # The actual call goes through Hub to the target device
            import asyncio
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                # No running loop: use asyncio.run() so the loop is always closed.
                return asyncio.run(
                    self._hub_client.execute_remote_skill(
                        device_name=self._device_name,
                        skill_name=self._skill_name,
                        method_name=method_name,
                        args=list(args),
                        kwargs=kwargs,
                    )
                )

            # Running loop in this thread.
            # Remote skill calls from sandbox require async bridge implementation.
            # This would need to use the sandbox's async bridge to call Hub.
            raise NotImplementedError(
                "Remote skill calls from sandbox require async bridge implementation. "
                f"Attempted: {self._device_name}.{self._skill_name}.{method_name}"
            )

            # (unreachable)
            if False:  # pragma: no cover
                # Remote skill calls from sandbox require async bridge implementation
                # This would need to use the sandbox's async bridge to call Hub
                ...

        return method_wrapper
