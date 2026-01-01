"""Bridge communication with Deno sandbox."""

import json
import asyncio
import logging
import uuid
from typing import Any, Dict, Callable, Optional, Awaitable

logger = logging.getLogger(__name__)


class BridgeError(Exception):
    """Error from bridge communication."""
    pass


class BridgeClient:
    """Handles JSON communication with Deno sandbox.
    
    Protocol:
    - Python → Deno: {"type": "execute", "id": "...", "data": {...}}
    - Deno → Python: {"type": "call", "id": "...", "data": {...}}
    - Python → Deno: {"type": "result", "id": "...", "data": {...}}
    - Deno → Python: {"type": "complete", "id": "...", "data": {...}}
    """
    
    def __init__(
        self,
        stdin: asyncio.StreamWriter,
        stdout: asyncio.StreamReader,
        call_handler: Callable[[str, list, dict], Any],
    ):
        """Initialize bridge client.
        
        Args:
            stdin: Writer to Deno process stdin
            stdout: Reader from Deno process stdout
            call_handler: Function to handle skill calls from sandbox
        """
        self.stdin = stdin
        self.stdout = stdout
        self.call_handler = call_handler
        
        self._pending: Dict[str, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self):
        """Start the message reader task."""
        self._running = True
        self._reader_task = asyncio.create_task(self._read_loop())
    
    async def stop(self):
        """Stop the reader task."""
        self._running = False
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        
        # Cancel pending requests
        for request_id, future in self._pending.items():
            if not future.done():
                future.set_exception(BridgeError("Bridge stopped"))
        self._pending.clear()
    
    async def execute(self, code: str, proxy_code: str) -> str:
        """Execute code and return output.
        
        Args:
            code: User code to execute
            proxy_code: Proxy injection code
            
        Returns:
            stdout output from execution
            
        Raises:
            BridgeError: On communication error
            RuntimeError: On execution error in sandbox
        """
        request_id = str(uuid.uuid4())
        
        # Create future for response
        future: asyncio.Future = asyncio.Future()
        self._pending[request_id] = future
        
        try:
            # Send execute request
            message = {
                "type": "execute",
                "id": request_id,
                "data": {
                    "code": code,
                    "proxy": proxy_code,
                }
            }
            
            await self._send(message)
            
            # Wait for completion
            return await future
            
        except Exception as e:
            # Clean up pending request
            self._pending.pop(request_id, None)
            raise
    
    async def _send(self, message: dict):
        """Send JSON message to Deno."""
        line = json.dumps(message) + "\n"
        self.stdin.write(line.encode())
        await self.stdin.drain()
        logger.debug(f"[Bridge TX] {message['type']} id={message['id']}")
    
    async def _read_loop(self):
        """Read and handle messages from Deno."""
        while self._running:
            try:
                line = await self.stdout.readline()
                if not line:
                    logger.warning("Bridge: stdout closed")
                    break
                
                try:
                    message = json.loads(line.decode())
                    await self._handle_message(message)
                except json.JSONDecodeError as e:
                    logger.error(f"Bridge: Invalid JSON: {line!r}")
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Bridge read error: {e}")
    
    async def _handle_message(self, message: dict):
        """Handle incoming message from Deno."""
        msg_type = message.get("type")
        msg_id = message.get("id")
        data = message.get("data", {})
        
        logger.debug(f"[Bridge RX] {msg_type} id={msg_id}")
        
        if msg_type == "call":
            # Skill call from sandbox - handle and respond
            await self._handle_call(msg_id, data)
        
        elif msg_type == "complete":
            # Execution complete
            if msg_id in self._pending:
                self._pending[msg_id].set_result(data.get("output", ""))
                del self._pending[msg_id]
            else:
                logger.warning(f"Bridge: Unknown request id: {msg_id}")
        
        elif msg_type == "error":
            # Execution error
            if msg_id in self._pending:
                error_msg = data.get("error", "Unknown error")
                self._pending[msg_id].set_exception(RuntimeError(error_msg))
                del self._pending[msg_id]
            else:
                logger.warning(f"Bridge: Unknown request id: {msg_id}")
        
        else:
            logger.warning(f"Bridge: Unknown message type: {msg_type}")
    
    async def _handle_call(self, msg_id: str, data: dict):
        """Handle a skill call from the sandbox."""
        path = data.get("path")
        args = data.get("args", [])
        kwargs = data.get("kwargs", {})
        
        try:
            # Execute the call via handler
            result = self.call_handler(path, args, kwargs)
            
            # Handle async results
            if asyncio.iscoroutine(result):
                result = await result
            
            # Send result back
            await self._send({
                "type": "result",
                "id": msg_id,
                "data": {"value": result}
            })
            
        except Exception as e:
            logger.error(f"Bridge call error: {path} - {e}")
            await self._send({
                "type": "error", 
                "id": msg_id,
                "data": {"error": str(e)}
            })

