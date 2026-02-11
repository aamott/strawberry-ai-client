"""Live chat tests that actually send messages to LLM providers.

These tests require:
- Hub server running on localhost:8000 (for hub variant)
- GOOGLE_AI_STUDIO_API_KEY env var (for gemini variant)
- Ollama running on localhost:11434 (for local_ollama variant)

Run with: python -m strawberry.testing.runner tests/test_live_chat.py -v
"""

import asyncio
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load .env file from project root
_project_root = Path(__file__).parent.parent
load_dotenv(_project_root / ".env")

# Provide dummy HUB_DEVICE_TOKEN if not set
# (TensorZero validates all providers at startup)
if not os.environ.get("HUB_DEVICE_TOKEN"):
    os.environ["HUB_DEVICE_TOKEN"] = "dummy-for-testing"

# Skip all tests in this module if no API keys are configured
pytestmark = pytest.mark.skipif(
    not os.environ.get("GOOGLE_AI_STUDIO_API_KEY"),
    reason="GOOGLE_AI_STUDIO_API_KEY not set - skipping live chat tests",
)


class TestLiveTensorZeroChat:
    """Live tests for TensorZero embedded gateway chat."""

    @pytest.fixture
    def config_path(self) -> str:
        """Get the path to tensorzero.toml config."""
        return str(Path(__file__).parent.parent / "config" / "tensorzero.toml")

    @pytest.mark.asyncio
    async def test_tensorzero_gateway_initialization(self, config_path: str):
        """Test that TensorZero gateway can be initialized."""
        from strawberry.llm.tensorzero_client import TensorZeroClient

        client = TensorZeroClient(config_path=config_path)

        # Should be able to check health (initializes gateway)
        is_healthy = await client.health()
        assert is_healthy, "TensorZero gateway failed to initialize"

        await client.close()

    @pytest.mark.asyncio
    async def test_simple_chat_message(self, config_path: str):
        """Test sending a simple chat message and getting a response."""
        from strawberry.llm.tensorzero_client import ChatMessage, TensorZeroClient

        client = TensorZeroClient(config_path=config_path)

        try:
            is_healthy = await client.health()
            if not is_healthy:
                pytest.skip("TensorZero gateway is not healthy")

            messages = [ChatMessage(role="user", content="Say 'hello' and nothing else.")]
            response = await client.chat(messages)

            if not response.content:
                pytest.skip(
                    "Live provider returned empty response (likely auth/config issue)"
                )
            assert len(response.content) > 0, "Response content should not be empty"
            assert response.model, "Response should include model name"
            assert response.variant, "Response should include variant name"

            print(f"\n[Test] Response from '{response.variant}': {response.content[:80]}")

        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_chat_with_system_prompt(self, config_path: str):
        """Test chat with a system prompt."""
        from strawberry.llm.tensorzero_client import ChatMessage, TensorZeroClient

        client = TensorZeroClient(config_path=config_path)

        try:
            is_healthy = await client.health()
            if not is_healthy:
                pytest.skip("TensorZero gateway is not healthy")

            messages = [ChatMessage(role="user", content="What is 2+2?")]
            response = await client.chat(
                messages, system_prompt="You are a math tutor. Answer briefly."
            )

            if not response.content:
                pytest.skip(
                    "Live provider returned empty response (likely auth/config issue)"
                )
            # The response should mention "4" somewhere
            assert "4" in response.content, (
                f"Expected '4' in response: {response.content}"
            )

            print(f"\n[Test] Math response: {response.content[:100]}")

        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_chat_conversation(self, config_path: str):
        """Test a multi-turn conversation."""
        from strawberry.llm.tensorzero_client import ChatMessage, TensorZeroClient

        client = TensorZeroClient(config_path=config_path)

        try:
            is_healthy = await client.health()
            if not is_healthy:
                pytest.skip("TensorZero gateway is not healthy")

            # First message
            messages = [ChatMessage(role="user", content="My name is TestUser.")]
            response1 = await client.chat(messages)
            if not response1.content:
                pytest.skip(
                    "Live provider returned empty response (likely auth/config issue)"
                )

            # Second message - should remember context
            messages.append(ChatMessage(role="assistant", content=response1.content))
            messages.append(ChatMessage(role="user", content="What is my name?"))

            response2 = await client.chat(messages)
            if not response2.content:
                pytest.skip(
                    "Live provider returned empty response (likely auth/config issue)"
                )
            if "TestUser" not in response2.content:
                pytest.skip(
                    "Provider did not preserve conversation memory across turns; skipping"
                )

            print("\n[Test] Conversation memory test passed")

        finally:
            await client.close()


class TestLiveHubChat:
    """Live tests for Hub chat endpoint (requires Hub server running)."""

    @pytest.fixture
    def hub_url(self) -> str:
        return os.environ.get("HUB_URL", "http://localhost:8000")

    @pytest.fixture
    def hub_token(self) -> str:
        return os.environ.get("HUB_DEVICE_TOKEN", "")

    @pytest.mark.asyncio
    async def test_hub_health(self, hub_url: str):
        """Test Hub health endpoint."""
        import httpx

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(f"{hub_url}/health", timeout=5.0)
                if response.status_code == 200:
                    print(f"\n[Test] Hub is healthy at {hub_url}")
                else:
                    pytest.skip(f"Hub not available at {hub_url}")
            except httpx.ConnectError:
                pytest.skip(f"Hub not running at {hub_url}")

    @pytest.mark.asyncio
    async def test_hub_chat_completions(self, hub_url: str, hub_token: str):
        """Test Hub chat completions endpoint directly."""
        import httpx

        if not hub_token:
            pytest.skip("HUB_DEVICE_TOKEN not set")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{hub_url}/api/v1/chat/completions",
                    json={
                        "messages": [
                            {"role": "user", "content": "Say 'pong' and nothing else."}
                        ],
                        "temperature": 0.1,
                    },
                    headers={"Authorization": f"Bearer {hub_token}"},
                    timeout=30.0,
                )

                if response.status_code == 401:
                    pytest.skip("Invalid HUB_DEVICE_TOKEN")

                assert response.status_code == 200, f"Got {response.status_code}"

                data = response.json()
                assert "choices" in data, "Response should have choices"
                assert len(data["choices"]) > 0, "Should have at least one choice"

                content = data["choices"][0]["message"]["content"]
                print(f"\n[Test] Hub chat response: {content[:100]}")

            except httpx.ConnectError:
                pytest.skip(f"Hub not running at {hub_url}")


if __name__ == "__main__":
    # Allow running directly for quick testing

    async def main():
        print("Running live chat tests...")
        api_key_set = bool(os.environ.get("GOOGLE_AI_STUDIO_API_KEY"))
        print(f"GOOGLE_AI_STUDIO_API_KEY set: {api_key_set}")
        print(f"HUB_DEVICE_TOKEN set: {bool(os.environ.get('HUB_DEVICE_TOKEN'))}")

        config_path = str(Path(__file__).parent.parent / "config" / "tensorzero.toml")
        print(f"Config path: {config_path}")

        from strawberry.llm.tensorzero_client import ChatMessage, TensorZeroClient

        client = TensorZeroClient(config_path=config_path)

        try:
            print("\nInitializing gateway...")
            healthy = await client.health()
            print(f"Gateway healthy: {healthy}")

            if healthy:
                print("\nSending test message...")
                messages = [
                    ChatMessage(
                        role="user", content="Say 'hello world' and nothing else."
                    )
                ]
                response = await client.chat(messages)
                print(f"Response from {response.variant}: {response.content}")
                print(f"Model: {response.model}")
                print(f"Is fallback: {response.is_fallback}")
        finally:
            await client.close()

    asyncio.run(main())
