"""Skill service for managing skill lifecycle and LLM integration."""

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass

from .loader import SkillLoader, SkillInfo
from ..hub import HubClient

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
    SYSTEM_PROMPT_TEMPLATE = '''You are Strawberry, a helpful AI assistant with access to skills (functions) on this device.

## Available Skills

When the user asks you to do something that requires a skill, you can call it using Python code blocks.
Wrap skill calls in ```python code blocks. I will execute them and provide the results.

{skill_descriptions}

## How to Call Skills

Use the `device` object to call skills:

```python
# Example: Get the current time
result = device.TimeSkill.get_current_time()
print(result)
```

```python
# Example: Do math
result = device.CalculatorSkill.add(5, 3)
print(result)
```

## Important Rules

1. Only call skills that are listed above
2. Always use `device.SkillName.function_name()` format
3. Use `print()` to output results you want to share
4. If a skill fails, explain the error to the user
5. You can call multiple skills in sequence if needed

If the user's request doesn't require a skill, just respond normally with text.'''

    def __init__(
        self,
        skills_path: Path,
        hub_client: Optional[HubClient] = None,
        heartbeat_interval: float = 300.0,  # 5 minutes
    ):
        """Initialize skill service.
        
        Args:
            skills_path: Path to skills directory
            hub_client: Hub client for registration (optional)
            heartbeat_interval: Seconds between heartbeats
        """
        self.skills_path = Path(skills_path)
        self.hub_client = hub_client
        self.heartbeat_interval = heartbeat_interval
        
        self._loader = SkillLoader(skills_path)
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._registered = False
        self._skills_loaded = False
    
    def load_skills(self) -> List[SkillInfo]:
        """Load all skills from the skills directory.
        
        Returns:
            List of loaded skills
        """
        skills = self._loader.load_all()
        self._skills_loaded = True
        logger.info(f"Loaded {len(skills)} skills from {self.skills_path}")
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
        
        Args:
            response: LLM response text
            
        Returns:
            List of code blocks to execute
        """
        # Match ```python ... ``` code blocks
        pattern = r'```python\s*(.*?)```'
        matches = re.findall(pattern, response, re.DOTALL)
        return [m.strip() for m in matches if m.strip()]
    
    def execute_code(self, code: str) -> SkillCallResult:
        """Execute a code block containing skill calls.
        
        Creates a sandboxed environment with the `device` object available.
        
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
    
    def process_response(self, response: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Process LLM response, executing any skill calls.
        
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
        clean_response = re.sub(r'```python\s*.*?```', '', response, flags=re.DOTALL).strip()
        
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


class _DeviceProxy:
    """Proxy object for accessing skills from LLM-generated code.
    
    Allows: device.SkillName.method_name(args)
    """
    
    def __init__(self, loader: SkillLoader):
        self._loader = loader
    
    def __getattr__(self, name: str):
        """Get a skill class by name."""
        skill = self._loader.get_skill(name)
        if skill is None:
            raise AttributeError(f"Skill not found: {name}")
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

