"""Tests for Hub client."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from strawberry.hub.client import ChatMessage, HubClient, HubConfig, HubError


@pytest.fixture
def hub_config():
    """Create test Hub config."""
    return HubConfig(
        url="http://localhost:8000",
        token="test-token",
        timeout=5.0,
    )


@pytest.fixture
def mock_client():
    """Create a mock httpx client."""
    return MagicMock(spec=httpx.AsyncClient)


@pytest.fixture
def hub_client(hub_config, mock_client):
    """Create Hub client with mocked HTTP client."""
    client = HubClient(hub_config)
    client._client = mock_client
    return client


class TestHubConfig:
    """Tests for HubConfig."""

    def test_from_settings_with_config(self):
        """Test creating config from settings."""
        settings = MagicMock()
        settings.hub_url = "http://hub:8000"
        settings.hub_token = "token123"
        settings.hub_timeout = 15.0

        config = HubConfig.from_settings(settings)

        assert config is not None
        assert config.url == "http://hub:8000"
        assert config.token == "token123"
        assert config.timeout == 15.0

    def test_from_settings_without_url(self):
        """Test returns None if Hub not configured."""
        settings = MagicMock()
        settings.hub_url = None
        settings.hub_token = "token"

        config = HubConfig.from_settings(settings)

        assert config is None

    def test_from_settings_without_token(self):
        """Test returns None if token not configured."""
        settings = MagicMock()
        settings.hub_url = "http://hub:8000"
        settings.hub_token = None

        config = HubConfig.from_settings(settings)

        assert config is None


class TestHubClientHealth:
    """Tests for health check."""

    @pytest.mark.asyncio
    async def test_health_success(self, hub_client, mock_client):
        """Test health check returns True when Hub is healthy."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False

        result = await hub_client.health()

        assert result is True
        mock_client.get.assert_called_once_with("/health")

    @pytest.mark.asyncio
    async def test_health_failure(self, hub_client, mock_client):
        """Test health check returns False when Hub is down."""
        mock_client.get = AsyncMock(side_effect=httpx.RequestError("Connection refused"))
        mock_client.is_closed = False

        result = await hub_client.health()

        assert result is False


class TestHubClientChat:
    """Tests for chat functionality."""

    def test_build_chat_payload_includes_session_id(self, hub_client):
        """Payload builder should include session_id when provided."""
        messages = [ChatMessage(role="user", content="hello")]
        payload = hub_client._build_chat_payload(
            messages=messages,
            temperature=0.7,
            enable_tools=True,
            stream=True,
            model=None,
            max_tokens=None,
            session_id="session-123",
        )
        assert payload["session_id"] == "session-123"

    @pytest.mark.asyncio
    async def test_chat_success(self, hub_client, mock_client):
        """Test successful chat request."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "chatcmpl-123",
            "model": "gpt-4o-mini",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello! How can I help?"},
                    "finish_reason": "stop",
                }
            ],
        }
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False

        messages = [ChatMessage(role="user", content="Hello")]
        response = await hub_client.chat(messages)

        assert response.content == "Hello! How can I help?"
        assert response.model == "gpt-4o-mini"
        assert response.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_chat_simple(self, hub_client, mock_client):
        """Test simple chat helper."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "model": "gpt-4o-mini",
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Hi there!"},
                    "finish_reason": "stop",
                }
            ],
        }
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False

        response = await hub_client.chat_simple("Hello")

        assert response == "Hi there!"

    @pytest.mark.asyncio
    async def test_chat_error(self, hub_client, mock_client):
        """Test chat error handling."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"detail": "LLM error"}
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False

        messages = [ChatMessage(role="user", content="Hello")]

        with pytest.raises(HubError) as exc_info:
            await hub_client.chat(messages)

        assert exc_info.value.status_code == 500
        assert "LLM error" in str(exc_info.value)


class TestHubClientSkills:
    """Tests for skill management."""

    @pytest.mark.asyncio
    async def test_register_skills(self, hub_client, mock_client):
        """Test skill registration."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": "Registered 2 skills"}
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False

        skills = [
            {"class_name": "TestSkill", "function_name": "test", "signature": "test()"},
        ]
        result = await hub_client.register_skills(skills)

        assert "Registered" in result["message"]

    @pytest.mark.asyncio
    async def test_search_skills(self, hub_client, mock_client):
        """Test skill search."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "path": "MusicSkill.play",
                    "signature": "play()",
                    "summary": "Play music",
                    "docstring": "Play music",
                    "devices": ["device1"],
                    "device_names": ["Device 1"],
                    "device_count": 1,
                    "is_local": False,
                },
            ],
            "total": 1,
        }
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False

        results = await hub_client.search_skills("music", device_limit=10)

        mock_client.get.assert_awaited_with(
            "/skills/search",
            params={"query": "music", "device_limit": 10},
        )

        assert len(results) == 1
        assert results[0]["path"] == "MusicSkill.play"


class _MockStreamingErrorResponse:
    """Streaming response mock that requires aread() before json/text access."""

    def __init__(self) -> None:
        self.status_code = 400
        self._read_called = False

    async def aread(self) -> bytes:
        self._read_called = True
        return b'{"detail":"bad request"}'

    def json(self) -> dict[str, str]:
        if not self._read_called:
            raise RuntimeError("read() not called")
        return {"detail": "bad request"}

    @property
    def text(self) -> str:
        if not self._read_called:
            raise RuntimeError("read() not called")
        return "bad request"

    def aiter_lines(self):
        async def _empty() -> AsyncMock:  # pragma: no cover
            if False:
                yield ""

        return _empty()


class _MockStreamContext:
    """Async context manager wrapper for stream response mocks."""

    def __init__(self, response) -> None:
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, exc_type, exc, tb):
        return False


class TestHubClientChatStream:
    """Tests for streaming chat behavior."""

    @pytest.mark.asyncio
    async def test_chat_stream_reads_error_body_before_check(
        self,
        hub_client,
        mock_client,
    ):
        """Streaming errors should not fail with unread response content access."""
        error_response = _MockStreamingErrorResponse()
        mock_client.stream.return_value = _MockStreamContext(error_response)
        mock_client.is_closed = False

        stream = hub_client.chat_stream(
            messages=[ChatMessage(role="user", content="hello")],
            enable_tools=True,
        )

        with pytest.raises(HubError) as exc_info:
            await stream.__anext__()

        assert error_response._read_called is True
        assert exc_info.value.status_code == 400
        assert "bad request" in str(exc_info.value)
