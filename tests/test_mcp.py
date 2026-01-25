"""Tests for MCP integration module."""

from unittest.mock import MagicMock, patch

import pytest

from strawberry.mcp.adapter import MCPSkillAdapter
from strawberry.mcp.client import MCPClient, MCPTool, MCPToolResult
from strawberry.mcp.config import MCPServerConfig
from strawberry.mcp.registry import MCPRegistry


class TestMCPServerConfig:
    """Tests for MCPServerConfig."""

    def test_basic_config(self):
        """Test creating a basic config."""
        config = MCPServerConfig(
            name="test-server",
            command="python",
            args=["-m", "test_server"],
        )
        assert config.name == "test-server"
        assert config.command == "python"
        assert config.args == ["-m", "test_server"]
        assert config.enabled is True
        assert config.transport == "stdio"

    def test_skill_name_conversion(self):
        """Test server name to skill name conversion."""
        config = MCPServerConfig(name="brave-search", command="npx")
        assert config.skill_name == "BraveSearchMCP"

        config2 = MCPServerConfig(name="file_system", command="npx")
        assert config2.skill_name == "FileSystemMCP"

        config3 = MCPServerConfig(name="context7", command="npx")
        assert config3.skill_name == "Context7MCP"

    def test_env_resolution(self):
        """Test environment variable resolution."""
        import os
        os.environ["TEST_API_KEY"] = "secret123"

        config = MCPServerConfig(
            name="test",
            command="cmd",
            env={"API_KEY": "${TEST_API_KEY}", "STATIC": "value"},
        )

        resolved = config.get_resolved_env()
        assert resolved["API_KEY"] == "secret123"
        assert resolved["STATIC"] == "value"

        del os.environ["TEST_API_KEY"]

    def test_missing_env_resolves_empty(self):
        """Test that missing env vars resolve to empty string."""
        config = MCPServerConfig(
            name="test",
            command="cmd",
            env={"MISSING": "${NONEXISTENT_VAR}"},
        )
        resolved = config.get_resolved_env()
        assert resolved["MISSING"] == ""

    def test_validation_requires_name(self):
        """Test that name is required."""
        with pytest.raises(ValueError, match="name is required"):
            MCPServerConfig(name="", command="cmd")

    def test_validation_requires_command_for_stdio(self):
        """Test that command is required for stdio transport."""
        with pytest.raises(ValueError, match="command is required"):
            MCPServerConfig(name="test", command="", transport="stdio")

    def test_validation_requires_url_for_sse(self):
        """Test that URL is required for SSE transport."""
        with pytest.raises(ValueError, match="url is required"):
            MCPServerConfig(name="test", command="", transport="sse")

    def test_sse_config_valid(self):
        """Test valid SSE configuration."""
        config = MCPServerConfig(
            name="test",
            command="",
            transport="sse",
            url="http://localhost:8080/sse",
        )
        assert config.transport == "sse"
        assert config.url == "http://localhost:8080/sse"

    def test_to_dict_roundtrip(self):
        """Test serialization roundtrip."""
        config = MCPServerConfig(
            name="test",
            command="cmd",
            args=["--arg1"],
            env={"KEY": "value"},
            timeout=60.0,
        )
        data = config.to_dict()
        restored = MCPServerConfig.from_dict(data)

        assert restored.name == config.name
        assert restored.command == config.command
        assert restored.args == config.args
        assert restored.env == config.env
        assert restored.timeout == config.timeout


class TestMCPSkillAdapter:
    """Tests for MCPSkillAdapter."""

    def test_tool_to_skill_info(self):
        """Test converting tools to SkillInfo."""
        adapter = MCPSkillAdapter()
        tools = [
            MCPTool(
                name="search",
                description="Search the web",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "count": {"type": "integer", "default": 10},
                    },
                    "required": ["query"],
                },
            ),
            MCPTool(
                name="get_result",
                description="Get a specific result",
                input_schema={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                    },
                    "required": ["id"],
                },
            ),
        ]

        skill_info = adapter.as_skill_info("brave-search", tools)

        assert skill_info.name == "BraveSearchMCP"
        assert len(skill_info.methods) == 2

        search_method = next(m for m in skill_info.methods if m.name == "search")
        assert "query: str" in search_method.signature
        assert "count: int = 10" in search_method.signature
        assert search_method.docstring == "Search the web"

    def test_schema_to_signature_required_params(self):
        """Test signature generation with required params."""
        adapter = MCPSkillAdapter()
        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
            "required": ["path"],
        }

        sig = adapter._schema_to_signature("read_file", schema)
        assert sig == "read_file(path: str)"

    def test_schema_to_signature_optional_params(self):
        """Test signature generation with optional params."""
        adapter = MCPSkillAdapter()
        schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        }

        sig = adapter._schema_to_signature("search", schema)
        assert "query: str" in sig
        assert "limit: int = 10" in sig

    def test_schema_to_signature_no_schema(self):
        """Test signature with empty schema."""
        adapter = MCPSkillAdapter()
        sig = adapter._schema_to_signature("tool", {})
        assert sig == "tool(**kwargs)"

    def test_json_type_mapping(self):
        """Test JSON type to Python type mapping."""
        adapter = MCPSkillAdapter()

        assert adapter._json_type_to_python({"type": "string"}) == "str"
        assert adapter._json_type_to_python({"type": "integer"}) == "int"
        assert adapter._json_type_to_python({"type": "number"}) == "float"
        assert adapter._json_type_to_python({"type": "boolean"}) == "bool"
        assert adapter._json_type_to_python({"type": "array"}) == "List[Any]"
        assert adapter._json_type_to_python({"type": "object"}) == "dict"

    def test_json_type_array_with_items(self):
        """Test array type with item type."""
        adapter = MCPSkillAdapter()
        result = adapter._json_type_to_python({
            "type": "array",
            "items": {"type": "string"},
        })
        assert result == "List[str]"

    def test_skill_name_to_server_name(self):
        """Test converting skill name back to server name."""
        adapter = MCPSkillAdapter()

        assert adapter._to_server_name("BraveSearchMCP") == "brave-search"
        assert adapter._to_server_name("FilesystemMCP") == "filesystem"
        assert adapter._to_server_name("Context7MCP") == "context7"


class TestMCPRegistry:
    """Tests for MCPRegistry."""

    def test_add_server(self):
        """Test adding server configs."""
        registry = MCPRegistry()
        config = MCPServerConfig(name="test", command="cmd")

        registry.add_server(config)
        assert registry.server_count == 1

    def test_init_with_configs(self):
        """Test initializing with configs."""
        configs = [
            MCPServerConfig(name="server1", command="cmd1"),
            MCPServerConfig(name="server2", command="cmd2"),
        ]
        registry = MCPRegistry(configs)
        assert registry.server_count == 2

    def test_has_skill_before_start(self):
        """Test has_skill returns False before starting."""
        registry = MCPRegistry([
            MCPServerConfig(name="test", command="cmd"),
        ])
        assert not registry.has_skill("TestMCP")

    @pytest.mark.asyncio
    async def test_start_disabled_server(self):
        """Test that disabled servers are skipped."""
        registry = MCPRegistry([
            MCPServerConfig(name="test", command="cmd", enabled=False),
        ])

        results = await registry.start_all()
        assert results["test"] is False
        assert registry.connected_count == 0

    @pytest.mark.asyncio
    async def test_get_status(self):
        """Test getting server status."""
        registry = MCPRegistry([
            MCPServerConfig(name="test", command="cmd", enabled=True),
        ])

        status = registry.get_status()
        assert "test" in status
        assert status["test"]["configured"] is True
        assert status["test"]["enabled"] is True
        assert status["test"]["connected"] is False
        assert status["test"]["skill_name"] == "TestMCP"


class TestMCPClient:
    """Tests for MCPClient."""

    def test_init(self):
        """Test client initialization."""
        config = MCPServerConfig(name="test", command="cmd")
        client = MCPClient(config)

        assert client.config == config
        assert not client.connected
        assert client.tools == []

    @pytest.mark.asyncio
    async def test_start_without_mcp_package(self):
        """Test that start raises ImportError without mcp package."""
        config = MCPServerConfig(name="test", command="cmd")
        client = MCPClient(config)

        # Mock the import to fail
        with patch.dict("sys.modules", {"mcp": None}):
            with patch("builtins.__import__", side_effect=ImportError("No mcp")):
                with pytest.raises(ImportError, match="MCP package not installed"):
                    await client.start()

    def test_extract_content_single_text(self):
        """Test extracting content from single text result."""
        config = MCPServerConfig(name="test", command="cmd")
        client = MCPClient(config)

        mock_result = MagicMock()
        mock_item = MagicMock()
        mock_item.text = "Hello, world!"
        mock_result.content = [mock_item]

        content = client._extract_content(mock_result)
        assert content == "Hello, world!"

    def test_extract_content_multiple(self):
        """Test extracting content from multiple items."""
        config = MCPServerConfig(name="test", command="cmd")
        client = MCPClient(config)

        mock_result = MagicMock()
        mock_item1 = MagicMock()
        mock_item1.text = "Line 1"
        mock_item2 = MagicMock()
        mock_item2.text = "Line 2"
        mock_result.content = [mock_item1, mock_item2]

        content = client._extract_content(mock_result)
        assert content == ["Line 1", "Line 2"]

    def test_extract_content_empty(self):
        """Test extracting content from empty result."""
        config = MCPServerConfig(name="test", command="cmd")
        client = MCPClient(config)

        mock_result = MagicMock()
        mock_result.content = []

        content = client._extract_content(mock_result)
        assert content is None


class TestMCPToolResult:
    """Tests for MCPToolResult."""

    def test_success_result(self):
        """Test creating a success result."""
        result = MCPToolResult(success=True, content="data")
        assert result.success is True
        assert result.content == "data"
        assert result.error is None

    def test_error_result(self):
        """Test creating an error result."""
        result = MCPToolResult(success=False, error="Something went wrong")
        assert result.success is False
        assert result.error == "Something went wrong"


class TestMCPTool:
    """Tests for MCPTool dataclass."""

    def test_basic_tool(self):
        """Test creating a basic tool."""
        tool = MCPTool(
            name="search",
            description="Search for items",
            input_schema={"type": "object"},
        )
        assert tool.name == "search"
        assert tool.description == "Search for items"

    def test_tool_defaults(self):
        """Test tool default values."""
        tool = MCPTool(name="test")
        assert tool.description == ""
        assert tool.input_schema == {}
