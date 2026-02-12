"""Skill service for managing skill lifecycle and LLM integration."""

from __future__ import annotations

import ast
import asyncio
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..hub import HubClient
from .loader import SkillInfo, SkillLoader
from .prompt import DEFAULT_SYSTEM_PROMPT_TEMPLATE, build_system_prompt
from .proxies import (
    DeviceProxy,
    SkillCallResult,
    normalize_device_name,
)
from .sandbox.executor import SandboxConfig, SandboxExecutor
from .sandbox.gatekeeper import Gatekeeper
from .sandbox.proxy_gen import ProxyGenerator, SkillMode
from .tool_dispatch import enrich_exec_error, format_search_results

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
__all__ = ["SkillService", "SkillCallResult", "normalize_device_name"]


class SkillService:
    """Manages skill loading, registration, and execution.

    Responsibilities:
    - Load skills from Python files
    - Register skills with Hub
    - Send heartbeats to keep skills alive
    - Generate system prompt for LLM
    - Parse and execute skill calls from LLM responses
    """

    # Re-export from prompt module for backward compatibility
    DEFAULT_SYSTEM_PROMPT_TEMPLATE = DEFAULT_SYSTEM_PROMPT_TEMPLATE

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
        settings_manager: Optional[Any] = None,
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
            settings_manager: Optional SettingsManager for skill settings.
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

        self._loader = SkillLoader(skills_path, settings_manager=settings_manager)
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

        # Register skill settings schemas with SettingsManager
        registered = self._loader.register_skill_settings()
        if registered:
            logger.info("Registered settings for %d skill(s)", registered)

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
            summaries.append(
                {
                    "name": skill.name,
                    "method_count": len(skill.methods),
                    "enabled": skill.name not in self._disabled_skills,
                    "source": str(skill.module_path) if skill.module_path else "unknown",
                    "methods": [
                        {
                            "name": m.name,
                            "signature": m.signature,
                            "docstring": m.docstring,
                        }
                        for m in skill.methods
                    ],
                    "healthy": health.get("healthy", True),
                    "health_message": health.get("message", ""),
                }
            )
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

    def _build_tool_call_info(self, code: str, result: SkillCallResult) -> Dict[str, Any]:
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

        Delegates to :func:`prompt.build_system_prompt`.

        Returns:
            System prompt string for LLM
        """
        self._ensure_skills_loaded()
        skills = self.get_all_skills()
        mode = self._get_effective_mode()
        return build_system_prompt(
            skills=skills,
            mode=mode,
            device_name=self.device_name,
            custom_template=self._custom_system_prompt,
            mode_notice=mode_notice,
        )

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
        fenced_pattern = r"```(?:python|tool_code|code|py)?\s*(.*?)\s*```"
        fenced_matches = re.findall(fenced_pattern, response, re.DOTALL | re.IGNORECASE)
        code_blocks.extend([m.strip() for m in fenced_matches if m.strip()])

        # 2. If no fenced blocks found, look for bare device.* calls
        if not code_blocks:
            mode = self._get_effective_mode()
            allowed_roots = ("device",)
            if mode == SkillMode.REMOTE:
                allowed_roots = ("device", "devices", "device_manager")

            # Match lines like: print(device.X...) or device.X...
            bare_pattern = (
                r"^[\s]*((?:print\s*\()?\s*(?:" + "|".join(allowed_roots) + r")\."
                r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\s*\([^)]*\)\s*\)?)"
            )
            for line in response.split("\n"):
                match = re.match(bare_pattern, line.strip())
                if match:
                    code = match.group(1).strip()
                    # Ensure print() wrapper for output
                    if not code.startswith("print("):
                        code = f"print({code})"
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
        device = DeviceProxy(self._loader)

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
            # For now, conservatively allow if local
            # device is referenced (a more sophisticated
            # check would parse the AST)
            return False

        # Contains devices. but not our local device - must be remote
        return True

    async def process_response_async(
        self, response: str
    ) -> Tuple[str, List[Dict[str, Any]]]:
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
            raise RuntimeError(f"{skill_name}.{method_name} failed: {msg}") from e

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
                    return {"error": enrich_exec_error(result.error or "")}

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
            self._gatekeeper.set_device_manager(self._build_device_manager())
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
                        "To call a skill method like multiply,"
                        " use python_exec with code like: "
                        "print(device.CalculatorSkill"
                        ".multiply(a=5, b=3))"
                    )
                }

        except Exception as e:
            import traceback

            return {"error": f"{type(e).__name__}: {e}\n{traceback.format_exc()}"}

    async def _tool_search_skills(
        self,
        arguments: Dict[str, Any],
        mode: "SkillMode",
    ) -> Dict[str, Any]:
        """Handle the search_skills tool call."""
        query = arguments.get("query", "")
        device_limit = int(arguments.get("device_limit", 10) or 10)
        if mode == SkillMode.REMOTE and self.hub_client:
            results = await self.hub_client.search_skills(
                query=query,
                device_limit=device_limit,
            )
            return {"result": format_search_results(results)}

        result = self._execute_search_skills(query, device_limit=device_limit)
        return {"result": result}

    async def _tool_describe_function(
        self,
        arguments: Dict[str, Any],
        mode: "SkillMode",
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
            query=query,
            device_limit=10,
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

                return {"result": (f'def {signature}:\n    """{doc}"""' + devices_info)}

        return {"error": f"Function not found: {path}"}

    async def _tool_python_exec(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle the python_exec tool call."""
        code = arguments.get("code", "")
        code = self._prepare_python_exec_code(code)
        result = await self.execute_code_async(code)
        if result.success:
            return {"result": result.result or "(no output)"}
        else:
            return {"error": enrich_exec_error(result.error or "")}

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
        device = DeviceProxy(self._loader)
        results = device.search_skills(query, device_limit=device_limit)

        return format_search_results(results)

    def _execute_describe_function(self, path: str) -> str:
        """Execute describe_function tool.

        Args:
            path: Function path (SkillName.method_name)

        Returns:
            Function description string
        """
        self._ensure_skills_loaded()

        device = DeviceProxy(self._loader)
        return device.describe_function(path)
