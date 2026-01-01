"""Skill service for managing skill lifecycle and LLM integration."""

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..hub import HubClient
from .loader import SkillInfo, SkillLoader
from .sandbox import Gatekeeper, ProxyGenerator, SandboxConfig, SandboxExecutor

logger = logging.getLogger(__name__)


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

    # System prompt template for skills
    SYSTEM_PROMPT_TEMPLATE = '''You are Strawberry, a helpful AI assistant with access to skills on this device.

## How Skills Work

When you write a ```python code block, I will execute it and show you the output. Then you continue your response.

Example conversation:
- User: "What time is it?"
- You write: ```python
result = device.TimeSkill.get_current_time()
print(result)
```
- I execute it and reply: "3:45 PM"
- You respond naturally: "The current time is 3:45 PM."

## Available Skills

{skill_descriptions}

## Discovery Commands

If you're not sure what skills exist:
```python
# Search for skills
results = device.search_skills("music")
print(results)
```

```python
# Get function details
info = device.describe_function("TimeSkill.get_current_time")
print(info)
```

## Rules

1. Always wrap code in ```python fences
2. Always use print() to see output
3. After I show you the output, respond naturally to the user (NO code block in your final response)
4. Keep responses concise and friendly'''

    def __init__(
        self,
        skills_path: Path,
        hub_client: Optional[HubClient] = None,
        heartbeat_interval: float = 300.0,  # 5 minutes
        use_sandbox: bool = True,
        sandbox_config: Optional[SandboxConfig] = None,
    ):
        """Initialize skill service.
        
        Args:
            skills_path: Path to skills directory
            hub_client: Hub client for registration (optional)
            heartbeat_interval: Seconds between heartbeats
            use_sandbox: Whether to use secure sandbox (default True)
            sandbox_config: Sandbox configuration (optional)
        """
        self.skills_path = Path(skills_path)
        self.hub_client = hub_client
        self.heartbeat_interval = heartbeat_interval
        self.use_sandbox = use_sandbox

        self._loader = SkillLoader(skills_path)
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._registered = False
        self._skills_loaded = False

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
            gatekeeper = Gatekeeper(self._loader)
            proxy_gen = ProxyGenerator(skills)
            self._sandbox = SandboxExecutor(
                gatekeeper=gatekeeper,
                proxy_generator=proxy_gen,
                config=self._sandbox_config,
            )
            logger.info("Sandbox executor initialized")

        return skills

    async def register_with_hub(self) -> bool:
        """Register loaded skills with the Hub.
        
        Returns:
            True if registration succeeded
        """
        if not self.hub_client:
            logger.warning("No Hub client - skipping skill registration")
            return False

        if not self._skills_loaded:
            self.load_skills()

        skills_data = self._loader.get_registration_data()

        if not skills_data:
            logger.info("No skills to register")
            return True

        try:
            result = await self.hub_client.register_skills(skills_data)
            self._registered = True
            logger.info(f"Registered {len(skills_data)} skill methods with Hub")
            return True
        except Exception as e:
            logger.error(f"Failed to register skills: {e}")
            return False

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

    def get_system_prompt(self) -> str:
        """Generate the system prompt with skill descriptions.
        
        Returns:
            System prompt string for LLM
        """
        if not self._skills_loaded:
            self.load_skills()

        skills = self._loader.get_all_skills()

        if not skills:
            return "You are Strawberry, a helpful AI assistant."

        # Build skill descriptions
        descriptions = []
        for skill in skills:
            descriptions.append(f"### {skill.name}")
            if skill.class_obj.__doc__:
                descriptions.append(skill.class_obj.__doc__.strip())
            descriptions.append("")

            for method in skill.methods:
                descriptions.append(f"- `device.{skill.name}.{method.signature}`")
                if method.docstring:
                    # Just first line of docstring
                    first_line = method.docstring.split('\n')[0].strip()
                    descriptions.append(f"  {first_line}")
            descriptions.append("")

        skill_text = "\n".join(descriptions)
        return self.SYSTEM_PROMPT_TEMPLATE.format(skill_descriptions=skill_text)

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
            # Match lines that look like: print(device.Something...) or device.Something...
            bare_pattern = r'^[\s]*((?:print\s*\()?\s*device\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\s*\([^)]*\)\s*\)?)'
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
            return SkillCallResult(
                success=result.success,
                result=result.output,
                error=result.error,
            )
        else:
            # Fallback to sync execution if sandbox not initialized
            return self.execute_code(code)

    def execute_code(self, code: str) -> SkillCallResult:
        """Execute a code block containing skill calls (sync, direct).
        
        WARNING: This method uses direct exec() and is NOT secure.
        Use execute_code_async() with sandbox for production.
        
        Args:
            code: Python code to execute
            
        Returns:
            SkillCallResult with output or error
        """
        import io
        import sys

        # Create device proxy
        device = _DeviceProxy(self._loader)

        # Capture stdout
        stdout_capture = io.StringIO()
        old_stdout = sys.stdout

        try:
            sys.stdout = stdout_capture

            # Execute in restricted namespace
            namespace = {
                'device': device,
                'print': print,
            }

            exec(code, namespace)

            output = stdout_capture.getvalue()
            return SkillCallResult(success=True, result=output.strip() if output else None)

        except Exception as e:
            return SkillCallResult(success=False, error=str(e))
        finally:
            sys.stdout = old_stdout

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

            tool_calls.append({
                "code": code,
                "success": result.success,
                "result": result.result,
                "error": result.error,
            })

            if result.success and result.result:
                results.append(f"Output:\n{result.result}")
            elif not result.success:
                results.append(f"Error: {result.error}")

        # Remove code blocks from response and append results
        clean_response = re.sub(r'```(?:python|tool_code|code|py)?\s*.*?```', '', response, flags=re.DOTALL | re.IGNORECASE).strip()

        if results:
            clean_response = clean_response + "\n\n" + "\n".join(results)

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

            tool_calls.append({
                "code": code,
                "success": result.success,
                "result": result.result,
                "error": result.error,
            })

            if result.success and result.result:
                results.append(f"Output:\n{result.result}")
            elif not result.success:
                results.append(f"Error: {result.error}")

        # Remove code blocks from response and append results
        clean_response = re.sub(r'```(?:python|tool_code|code|py)?\s*.*?```', '', response, flags=re.DOTALL | re.IGNORECASE).strip()

        if results:
            clean_response = clean_response + "\n\n" + "\n".join(results)

        return clean_response, tool_calls

    def get_skill(self, name: str) -> Optional[SkillInfo]:
        """Get a skill by class name."""
        return self._loader.get_skill(name)

    def get_all_skills(self) -> List[SkillInfo]:
        """Get all loaded skills."""
        if not self._skills_loaded:
            self.load_skills()
        return self._loader.get_all_skills()

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
        if not self._skills_loaded:
            self.load_skills()

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
            logger.error(f"Skill execution failed: {skill_name}.{method_name} - {e}")
            raise RuntimeError(f"Skill execution failed: {e}")


class _DeviceProxy:
    """Proxy object for accessing skills from LLM-generated code.
    
    Provides:
    - device.search_skills("query") - Find skills by keyword
    - device.describe_function("SkillName.method") - Get function details
    - device.SkillName.method_name(args) - Call a skill
    """

    def __init__(self, loader: SkillLoader):
        self._loader = loader

    def search_skills(self, query: str = "") -> List[Dict[str, Any]]:
        """Search for skills by keyword.
        
        Args:
            query: Search term (matches name, signature, docstring)
            
        Returns:
            List of matching skills with path, signature, summary
        """
        results = []
        for skill in self._loader.get_all_skills():
            for method in skill.methods:
                # Check if query matches
                query_lower = query.lower() if query else ""
                matches = (
                    not query or
                    query_lower in method.name.lower() or
                    query_lower in skill.name.lower() or
                    query_lower in method.signature.lower() or
                    (method.docstring and query_lower in method.docstring.lower())
                )

                if matches:
                    # Get first line of docstring as summary
                    summary = ""
                    if method.docstring:
                        summary = method.docstring.split("\n")[0].strip()

                    results.append({
                        "path": f"{skill.name}.{method.name}",
                        "signature": method.signature,
                        "summary": summary,
                    })
        return results

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
                return f"def {method.signature}:\n    \"\"\"\n    {doc}\n    \"\"\""

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
        self._loader = loader
        self._skill_name = skill_name

    def __getattr__(self, name: str):
        """Get a method that calls the actual skill."""
        def method_wrapper(*args, **kwargs):
            return self._loader.call_method(self._skill_name, name, *args, **kwargs)
        return method_wrapper

