"""Sandbox executor for secure code execution."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..proxies import DeviceProxy
from .bridge import BridgeClient, BridgeError
from .gatekeeper import Gatekeeper
from .process import DenoNotFoundError, DenoProcessManager
from .proxy_gen import ProxyGenerator

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result from sandbox execution."""

    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    timed_out: bool = False


@dataclass
class SandboxConfig:
    """Sandbox configuration."""

    # Hard-kill with no cleanup grace period (seconds)
    timeout_seconds: float = 5.0
    memory_limit_mb: int = 128
    deno_path: str = "deno"
    enabled: bool = True  # Can disable for development


class SandboxExecutor:
    """Executes LLM code in a secure Pyodide sandbox.

    Architecture:
    - Spawns Deno process hosting Pyodide (Wasm)
    - Communicates via JSON over stdin/stdout
    - Injects proxy objects for skill calls
    - Enforces timeout and resource limits

    Usage:
        executor = SandboxExecutor(gatekeeper, proxy_gen)
        result = await executor.execute("print(device.TimeSkill.get_time())")
    """

    def __init__(
        self,
        gatekeeper: Gatekeeper,
        proxy_generator: ProxyGenerator,
        config: Optional[SandboxConfig] = None,
    ):
        """Initialize sandbox executor.

        Args:
            gatekeeper: Validates and executes skill calls
            proxy_generator: Generates proxy code for injection
            config: Sandbox configuration
        """
        self.gatekeeper = gatekeeper
        self.proxy_generator = proxy_generator
        self.config = config or SandboxConfig()

        self._process_manager: Optional[DenoProcessManager] = None
        self._bridge: Optional[BridgeClient] = None
        self._initialized = False
        self._lock = asyncio.Lock()

    async def _ensure_initialized(self):
        """Ensure sandbox is initialized."""
        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return

            try:
                self._process_manager = DenoProcessManager(
                    deno_path=self.config.deno_path,
                    timeout=self.config.timeout_seconds,
                    memory_limit_mb=self.config.memory_limit_mb,
                )

                stdin, stdout = await self._process_manager.start()

                self._bridge = BridgeClient(
                    stdin=stdin,
                    stdout=stdout,
                    call_handler=self._handle_skill_call,
                )
                await self._bridge.start()

                self._initialized = True
                logger.info("Sandbox initialized successfully")

            except Exception as e:
                logger.error(f"Failed to initialize sandbox: {e}")
                await self._cleanup()
                raise

    async def _cleanup(self):
        """Clean up sandbox resources."""
        if self._bridge:
            await self._bridge.stop()
            self._bridge = None

        if self._process_manager:
            await self._process_manager.kill()
            self._process_manager = None

        self._initialized = False

    def _handle_skill_call(
        self, path: str, args: List[Any], kwargs: Dict[str, Any]
    ) -> Any:
        """Handle a skill call from the sandbox.

        Called by the bridge when guest code calls device.Skill.method().

        Args:
            path: "SkillClass.method_name"
            args: Positional arguments
            kwargs: Keyword arguments

        Returns:
            Result from skill execution
        """
        return self.gatekeeper.execute(path, args, kwargs)

    async def execute(self, code: str) -> ExecutionResult:
        """Execute code in the sandbox.

        Args:
            code: Python code to execute

        Returns:
            ExecutionResult with output or error
        """
        if not self.config.enabled:
            # Sandbox disabled - use direct execution (INSECURE)
            logger.warning("Sandbox disabled - using direct execution (INSECURE)")
            return self._execute_direct(code)

        try:
            # Initialize sandbox if needed
            await self._ensure_initialized()

            # Get proxy code
            proxy_code = self.proxy_generator.generate()

            # Execute with timeout
            try:
                output = await asyncio.wait_for(
                    self._bridge.execute(code, proxy_code),
                    timeout=self.config.timeout_seconds,
                )
                return ExecutionResult(
                    success=True, output=output.strip() if output else None
                )

            except asyncio.TimeoutError:
                logger.error(
                    f"Sandbox execution timeout ({self.config.timeout_seconds}s)"
                )
                # Kill and restart sandbox
                await self._cleanup()
                return ExecutionResult(
                    success=False,
                    error=f"Execution timeout ({self.config.timeout_seconds}s)",
                    timed_out=True,
                )

        except DenoNotFoundError as e:
            logger.error(f"Deno not found: {e}")
            return ExecutionResult(
                success=False,
                error=(
                    "Sandbox unavailable (Deno not installed). Install: "
                    "curl -fsSL https://deno.land/install.sh | sh"
                ),
            )

        except BridgeError as e:
            logger.error(f"Bridge error: {e}")
            await self._cleanup()
            return ExecutionResult(
                success=False, error=f"Sandbox communication error: {e}"
            )

        except RuntimeError as e:
            # Error from sandbox execution
            return ExecutionResult(success=False, error=self._sanitize_error(str(e)))

        except Exception as e:
            logger.error(f"Unexpected sandbox error: {e}", exc_info=True)
            return ExecutionResult(
                success=False, error=f"Sandbox error: {self._sanitize_error(str(e))}"
            )

    def _execute_direct(self, code: str) -> ExecutionResult:
        """Direct execution fallback (INSECURE - for development only).

        This bypasses the sandbox and executes code directly.
        Only use when sandbox is disabled for debugging.
        """
        import io
        import sys

        device = DeviceProxy(self.gatekeeper.loader)

        # Capture stdout
        stdout_capture = io.StringIO()
        old_stdout = sys.stdout

        try:
            sys.stdout = stdout_capture

            namespace = {
                "device": device,
                "print": print,
            }

            exec(code, namespace)

            output = stdout_capture.getvalue()
            return ExecutionResult(
                success=True, output=output.strip() if output else None
            )

        except Exception as e:
            return ExecutionResult(success=False, error=str(e))
        finally:
            sys.stdout = old_stdout

    def _sanitize_error(self, error: str) -> str:
        """Remove sensitive info from error messages."""
        import re

        # Remove file paths
        error = re.sub(r'File "[^"]+",', 'File "<sandbox>",', error)

        # Remove internal function references
        error = re.sub(r"in <module>|in \w+_proxy", "in <code>", error)

        # Limit length
        if len(error) > 500:
            error = error[:500] + "..."

        return error

    async def shutdown(self):
        """Shutdown the sandbox."""
        await self._cleanup()
        logger.info("Sandbox shutdown complete")

    def refresh_skills(self):
        """Refresh skill proxies after skill changes."""
        self.proxy_generator.invalidate()
        self.gatekeeper.refresh()
