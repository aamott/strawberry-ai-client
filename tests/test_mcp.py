"""Tests for MCP integration module.

Tests the simplified MCP wrapper that presents MCP servers as Python skill classes.
"""

from unittest.mock import MagicMock

from strawberry.mcp.adapter import MCPSkillAdapter, is_mcp_skill
from strawberry.mcp.client import MCPClient
from strawberry.mcp.config import MCPServerConfig
from strawberry.mcp.registry import MCPRegistry
from strawberry.mcp.settings import load_mcp_configs_from_settings, parse_mcp_config


class TestMCPServerConfig:
    """Tests for MCPServerConfig."""

    def test_basic_config(self):
        """Test creating a basic config."""
        config = MCPServerConfig(
            name="test_server",
            command="python",
            args=["-m", "test_server"],
        )
        assert config.name == "test_server"
        assert config.command == "python"
        assert config.args == ["-m", "test_server"]
        assert config.enabled is True
        assert config.env == {}

    def test_skill_class_name_conversion(self):
        """Test server name to skill class name conversion."""
        # Snake case
        config = MCPServerConfig(name="home_assistant", command="npx")
        assert config.get_skill_class_name() == "HomeAssistantMCP"

        # Simple name
        config2 = MCPServerConfig(name="firebase", command="npx")
        assert config2.get_skill_class_name() == "FirebaseMCP"

        # Single word
        config3 = MCPServerConfig(name="context7", command="npx")
        assert config3.get_skill_class_name() == "Context7MCP"

    def test_env_with_values(self):
        """Test config with environment variables."""
        config = MCPServerConfig(
            name="test",
            command="cmd",
            env={"API_KEY": "${TEST_API_KEY}", "STATIC": "value"},
        )
        assert config.env["API_KEY"] == "${TEST_API_KEY}"
        assert config.env["STATIC"] == "value"

    def test_disabled_config(self):
        """Test disabled config."""
        config = MCPServerConfig(
            name="test",
            command="cmd",
            enabled=False,
        )
        assert config.enabled is False


class TestMCPSkillAdapter:
    """Tests for MCPSkillAdapter."""

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
        assert "read_file(" in sig
        assert "path: str" in sig

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
        """Test signature with empty/None schema."""
        adapter = MCPSkillAdapter()
        sig = adapter._schema_to_signature("tool", None)
        assert sig == "tool() -> Any"

        sig2 = adapter._schema_to_signature("tool2", {})
        assert sig2 == "tool2() -> Any"

    def test_json_type_mapping(self):
        """Test JSON type to Python type mapping."""
        adapter = MCPSkillAdapter()

        assert adapter._json_type_to_python("string") == "str"
        assert adapter._json_type_to_python("integer") == "int"
        assert adapter._json_type_to_python("number") == "float"
        assert adapter._json_type_to_python("boolean") == "bool"
        assert adapter._json_type_to_python("array") == "List"
        assert adapter._json_type_to_python("object") == "Dict"
        assert adapter._json_type_to_python("null") == "None"
        assert adapter._json_type_to_python("unknown") == "Any"


class TestMCPRegistry:
    """Tests for MCPRegistry."""

    def test_init_with_configs(self):
        """Test initializing with configs."""
        configs = [
            MCPServerConfig(name="server1", command="cmd1"),
            MCPServerConfig(name="server2", command="cmd2"),
        ]
        registry = MCPRegistry(configs)
        assert len(registry.server_names) == 2
        assert "server1" in registry.server_names
        assert "server2" in registry.server_names

    def test_init_filters_disabled(self):
        """Test that disabled configs are filtered out."""
        configs = [
            MCPServerConfig(name="enabled", command="cmd1", enabled=True),
            MCPServerConfig(name="disabled", command="cmd2", enabled=False),
        ]
        registry = MCPRegistry(configs)
        assert len(registry.server_names) == 1
        assert "enabled" in registry.server_names

    def test_get_client_before_start(self):
        """Test get_client returns None before starting."""
        registry = MCPRegistry([
            MCPServerConfig(name="test", command="cmd"),
        ])
        assert registry.get_client("test") is None

    def test_get_all_skills_empty(self):
        """Test get_all_skills returns empty before starting."""
        registry = MCPRegistry([
            MCPServerConfig(name="test", command="cmd"),
        ])
        skills = registry.get_all_skills()
        assert skills == []

    def test_is_mcp_skill(self):
        """Test is_mcp_skill detection."""
        registry = MCPRegistry([])
        assert registry.is_mcp_skill("TestMCP") is False


class TestMCPClient:
    """Tests for MCPClient."""

    def test_init(self):
        """Test client initialization."""
        config = MCPServerConfig(name="test", command="cmd")
        client = MCPClient(config)

        assert client.config == config
        assert client.name == "test"
        assert client.skill_class_name == "TestMCP"
        assert not client.is_started
        assert client.tools == []

    def test_extract_result_single_text(self):
        """Test extracting result from single text content."""
        config = MCPServerConfig(name="test", command="cmd")
        client = MCPClient(config)

        mock_result = MagicMock()
        mock_item = MagicMock()
        mock_item.text = "Hello, world!"
        mock_result.content = [mock_item]

        content = client._extract_result(mock_result)
        assert content == "Hello, world!"

    def test_extract_result_multiple(self):
        """Test extracting result from multiple content items."""
        config = MCPServerConfig(name="test", command="cmd")
        client = MCPClient(config)

        mock_result = MagicMock()
        mock_item1 = MagicMock()
        mock_item1.text = "Line 1"
        del mock_item1.data  # Ensure no data attribute
        mock_item2 = MagicMock()
        mock_item2.text = "Line 2"
        del mock_item2.data
        mock_result.content = [mock_item1, mock_item2]

        content = client._extract_result(mock_result)
        assert len(content) == 2
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "Line 1"

    def test_extract_result_empty(self):
        """Test extracting result from empty content."""
        config = MCPServerConfig(name="test", command="cmd")
        client = MCPClient(config)

        mock_result = MagicMock()
        mock_result.content = []

        content = client._extract_result(mock_result)
        assert content is None

    def test_get_tool_not_found(self):
        """Test get_tool returns None for unknown tool."""
        config = MCPServerConfig(name="test", command="cmd")
        client = MCPClient(config)
        client.tools = []

        assert client.get_tool("unknown") is None


class TestParseMcpConfig:
    """Tests for parse_mcp_config."""

    def test_parse_valid_config(self):
        """Test parsing valid MCP config."""
        data = {
            "mcpServers": {
                "home_assistant": {
                    "command": "npx",
                    "args": ["-y", "@home-assistant/mcp-server"],
                    "env": {"HASS_TOKEN": "${HASS_TOKEN}"},
                },
                "firebase": {
                    "command": "node",
                    "args": ["firebase-mcp.js"],
                },
            }
        }

        configs = parse_mcp_config(data)
        assert len(configs) == 2

        ha_config = next(c for c in configs if c.name == "home_assistant")
        assert ha_config.command == "npx"
        assert ha_config.args == ["-y", "@home-assistant/mcp-server"]
        assert ha_config.env == {"HASS_TOKEN": "${HASS_TOKEN}"}

    def test_parse_empty_config(self):
        """Test parsing empty config."""
        configs = parse_mcp_config({})
        assert configs == []

        configs2 = parse_mcp_config({"mcpServers": {}})
        assert configs2 == []

    def test_parse_missing_command(self):
        """Test that missing command is skipped."""
        data = {
            "mcpServers": {
                "invalid": {
                    "args": ["some", "args"],
                }
            }
        }
        configs = parse_mcp_config(data)
        assert configs == []

    def test_parse_disabled_server(self):
        """Test parsing disabled server."""
        data = {
            "mcpServers": {
                "disabled_server": {
                    "command": "cmd",
                    "enabled": False,
                }
            }
        }
        configs = parse_mcp_config(data)
        assert len(configs) == 1
        assert configs[0].enabled is False

    def test_parse_disabled_flag_compat(self):
        """Test parsing `disabled` flag (compat with common MCP config format)."""
        data = {
            "mcpServers": {
                "disabled_server": {
                    "command": "cmd",
                    "disabled": True,
                },
                "enabled_server": {
                    "command": "cmd",
                    "disabled": False,
                },
            }
        }

        configs = parse_mcp_config(data)
        assert len(configs) == 2

        by_name = {cfg.name: cfg for cfg in configs}
        assert by_name["disabled_server"].enabled is False
        assert by_name["enabled_server"].enabled is True

    def test_parse_enabled_takes_precedence_over_disabled(self):
        """Test that `enabled` overrides `disabled` when both are provided."""
        data = {
            "mcpServers": {
                "server": {
                    "command": "cmd",
                    "enabled": True,
                    "disabled": True,
                }
            }
        }

        configs = parse_mcp_config(data)
        assert len(configs) == 1
        assert configs[0].enabled is True




class TestMcpConfigFileAutoCreation:
    """Tests for MCP config file auto-creation behavior."""

    def test_creates_file_at_settings_path_without_overwrite(self, tmp_path):
        """Ensure config file is created at settings path and not overwritten.

        This test simulates a SettingsManager that points `mcp.config_path`
        to a path inside a temp directory.
        """
        from strawberry.shared.settings import init_settings_manager

        settings = init_settings_manager(config_dir=tmp_path)
        settings.register("mcp", "MCP", [])

        # Use a nested path to ensure parent dirs are created
        target_config = tmp_path / "nested" / "mcp_config.json"
        settings.set("mcp", "config_path", str(target_config))

        # First load should create the file
        configs = load_mcp_configs_from_settings()
        assert configs == []
        assert target_config.exists()

        # Write sentinel content and ensure it remains after calling loader
        sentinel = '{"mcpServers": {"sentinel": {"command": "cmd"}}}'
        target_config.write_text(sentinel, encoding="utf-8")

        _ = load_mcp_configs_from_settings()
        assert target_config.read_text(encoding="utf-8") == sentinel


class TestIsMcpSkill:
    """Tests for is_mcp_skill helper."""

    def test_is_mcp_skill_true(self):
        """Test is_mcp_skill returns True for MCP skills."""
        from strawberry.skills.loader import SkillInfo

        skill = SkillInfo(name="HomeAssistantMCP", class_obj=type("Dummy", (), {}))
        assert is_mcp_skill(skill) is True

    def test_is_mcp_skill_false(self):
        """Test is_mcp_skill returns False for Python skills."""
        from strawberry.skills.loader import SkillInfo

        skill = SkillInfo(name="WeatherSkill", class_obj=type("Dummy", (), {}))
        assert is_mcp_skill(skill) is False
