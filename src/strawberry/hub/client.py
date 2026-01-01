"""HTTP client for communicating with the Strawberry AI Hub."""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import httpx


@dataclass
class HubConfig:
    """Configuration for Hub connection."""
    url: str
    token: str
    timeout: float = 30.0
    
    @classmethod
    def from_settings(cls, settings) -> Optional["HubConfig"]:
        """Create config from settings if Hub is configured."""
        if not settings.hub_url or not settings.hub_token:
            return None
        return cls(
            url=settings.hub_url,
            token=settings.hub_token,
            timeout=settings.hub_timeout,
        )


@dataclass
class ChatMessage:
    """A chat message."""
    role: str  # user, assistant, system
    content: str


@dataclass
class ChatResponse:
    """Response from chat endpoint."""
    content: str
    model: str
    finish_reason: str
    raw: Dict[str, Any] = field(default_factory=dict)


class HubError(Exception):
    """Error from Hub API."""
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class HubClient:
    """Client for communicating with the Strawberry AI Hub.
    
    Provides methods for:
    - Chat completions (LLM requests)
    - Skill registration
    - Skill discovery
    - Device management
    """
    
    def __init__(self, config: HubConfig):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None
    
    @property
    def client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.config.url,
                headers={"Authorization": f"Bearer {self.config.token}"},
                timeout=self.config.timeout,
            )
        return self._client
    
    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    # =========================================================================
    # Health & Info
    # =========================================================================
    
    async def health(self) -> bool:
        """Check if Hub is healthy."""
        try:
            response = await self.client.get("/health")
            return response.status_code == 200
        except httpx.RequestError:
            return False
    
    async def get_device_info(self) -> Dict[str, Any]:
        """Get information about the authenticated device."""
        response = await self.client.get("/auth/me")
        self._check_response(response)
        return response.json()
    
    # =========================================================================
    # Chat / LLM
    # =========================================================================
    
    async def chat(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> ChatResponse:
        """Send a chat completion request to the Hub.
        
        Args:
            messages: List of chat messages
            model: Model to use (default: Hub's configured model)
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response
            
        Returns:
            ChatResponse with the assistant's reply
        """
        payload = {
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
        }
        
        if model:
            payload["model"] = model
        if max_tokens:
            payload["max_tokens"] = max_tokens
        
        response = await self.client.post("/v1/chat/completions", json=payload)
        self._check_response(response)
        
        data = response.json()
        choice = data["choices"][0]
        
        return ChatResponse(
            content=choice["message"]["content"],
            model=data.get("model", "unknown"),
            finish_reason=choice.get("finish_reason", "stop"),
            raw=data,
        )
    
    async def chat_simple(self, user_message: str) -> str:
        """Simple chat - send a message and get a reply.
        
        Args:
            user_message: The user's message
            
        Returns:
            The assistant's reply text
        """
        response = await self.chat([ChatMessage(role="user", content=user_message)])
        return response.content
    
    # =========================================================================
    # Skills
    # =========================================================================
    
    async def register_skills(self, skills: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Register local skills with the Hub.
        
        Args:
            skills: List of skill definitions with:
                - class_name: Skill class name
                - function_name: Function name
                - signature: Function signature string
                - docstring: Optional docstring
                
        Returns:
            Registration result from Hub
        """
        response = await self.client.post(
            "/skills/register",
            json={"skills": skills},
        )
        self._check_response(response)
        return response.json()
    
    async def heartbeat(self) -> Dict[str, Any]:
        """Send heartbeat to keep skills alive."""
        response = await self.client.post("/skills/heartbeat")
        self._check_response(response)
        return response.json()
    
    async def list_skills(self, include_expired: bool = False) -> List[Dict[str, Any]]:
        """List all skills visible to this device.
        
        Args:
            include_expired: Include skills that haven't sent heartbeat recently
            
        Returns:
            List of skill definitions
        """
        response = await self.client.get(
            "/skills",
            params={"include_expired": str(include_expired).lower()},
        )
        self._check_response(response)
        return response.json()["skills"]
    
    async def search_skills(self, query: str = "") -> List[Dict[str, Any]]:
        """Search for skills across all devices.
        
        Args:
            query: Search query (matches function name, class name, docstring)
            
        Returns:
            List of matching skills with path, signature, summary, device
        """
        response = await self.client.get(
            "/skills/search",
            params={"query": query},
        )
        self._check_response(response)
        return response.json()["results"]
    
    # =========================================================================
    # Devices
    # =========================================================================
    
    async def list_devices(self) -> List[Dict[str, Any]]:
        """List all devices for the current user."""
        response = await self.client.get("/devices")
        self._check_response(response)
        return response.json()["devices"]
    
    # =========================================================================
    # Helpers
    # =========================================================================
    
    def _check_response(self, response: httpx.Response):
        """Check response for errors and raise HubError if needed."""
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise HubError(f"Hub API error: {detail}", response.status_code)

