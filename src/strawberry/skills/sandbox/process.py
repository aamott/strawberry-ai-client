"""Deno process management for the sandbox."""

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class DenoNotFoundError(Exception):
    """Raised when Deno is not installed or not in PATH."""

    pass


class DenoProcessManager:
    """Manages the Deno subprocess hosting Pyodide.

    Responsibilities:
    - Spawn/kill Deno process
    - Handle timeout/resource limits via Deno flags
    - Provide stdin/stdout streams for bridge
    """

    def __init__(
        self,
        deno_path: str = "deno",
        host_script: Optional[Path] = None,
        timeout: float = 5.0,
        memory_limit_mb: int = 128,
    ):
        self.deno_path = deno_path
        self.host_script = host_script or self._get_default_host_script()
        self.timeout = timeout
        self.memory_limit_mb = memory_limit_mb

        self._process: Optional[asyncio.subprocess.Process] = None
        self._stdin: Optional[asyncio.StreamWriter] = None
        self._stdout: Optional[asyncio.StreamReader] = None

    def _get_default_host_script(self) -> Path:
        """Get the default host.ts script path."""
        return Path(__file__).parent / "host.ts"

    @property
    def is_running(self) -> bool:
        """Check if the Deno process is running."""
        return self._process is not None and self._process.returncode is None

    def _verify_deno(self) -> str:
        """Verify Deno is available and return the path."""
        # Try to find deno
        deno = shutil.which(self.deno_path)
        if not deno:
            raise DenoNotFoundError(
                f"Deno not found at '{self.deno_path}'. "
                "Install Deno: curl -fsSL https://deno.land/install.sh | sh"
            )
        return deno

    async def start(self) -> Tuple[asyncio.StreamWriter, asyncio.StreamReader]:
        """Start Deno process.

        Returns:
            (stdin, stdout) streams for communication

        Raises:
            DenoNotFoundError: If Deno is not installed
            FileNotFoundError: If host script not found
        """
        if self.is_running:
            return self._stdin, self._stdout

        # Verify Deno and host script
        deno_path = self._verify_deno()

        if not self.host_script.exists():
            raise FileNotFoundError(f"Host script not found: {self.host_script}")

        # Deno command with security flags
        cmd = [
            deno_path,
            "run",
            # Security: Minimal permissions
            "--allow-read=" + str(self.host_script.parent),  # Only sandbox dir
            "--deny-net",  # No network access
            "--deny-env",  # No environment variables
            "--deny-run",  # Can't spawn processes
            "--deny-write",  # Can't write files
            "--no-prompt",  # Don't prompt for permissions
            # Resource limits via V8 flags
            f"--v8-flags=--max-old-space-size={self.memory_limit_mb}",
            str(self.host_script),
        ]

        logger.info(f"Starting Deno sandbox: {' '.join(cmd)}")

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self._stdin = self._process.stdin
        self._stdout = self._process.stdout

        # Start stderr reader for debugging
        asyncio.create_task(self._read_stderr())

        # Wait for ready signal
        try:
            ready_line = await asyncio.wait_for(
                self._stdout.readline(),
                timeout=30.0,  # Pyodide takes a while to load
            )
            if b"READY" not in ready_line:
                logger.warning(f"Unexpected ready signal: {ready_line}")
        except asyncio.TimeoutError:
            logger.error("Sandbox startup timeout")
            await self.kill()
            raise RuntimeError("Sandbox failed to start (timeout)")

        logger.info("Deno sandbox ready")
        return self._stdin, self._stdout

    async def _read_stderr(self):
        """Read and log stderr from Deno process."""
        if not self._process or not self._process.stderr:
            return

        while True:
            try:
                line = await self._process.stderr.readline()
                if not line:
                    break
                logger.debug(f"[Deno] {line.decode().strip()}")
            except Exception:
                break

    async def kill(self):
        """Kill the Deno process immediately."""
        if self._process:
            try:
                self._process.kill()
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except (ProcessLookupError, asyncio.TimeoutError):
                pass
            finally:
                self._process = None
                self._stdin = None
                self._stdout = None
                logger.info("Deno sandbox killed")

    async def restart(self) -> Tuple[asyncio.StreamWriter, asyncio.StreamReader]:
        """Kill and restart the process."""
        await self.kill()
        return await self.start()
