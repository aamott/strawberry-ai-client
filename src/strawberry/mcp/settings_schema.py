"""Settings schema for MCP configuration."""

from strawberry.shared.settings.schema import FieldType, SettingField

# MCP settings schema for the Settings UI
MCP_SETTINGS_SCHEMA = [
    SettingField(
        key="mcp.enabled",
        label="Enable MCP",
        type=FieldType.CHECKBOX,
        default=True,
        description="Enable Model Context Protocol server integration",
        group="general",
    ),
    SettingField(
        key="mcp.servers",
        label="MCP Servers",
        type=FieldType.MULTILINE,
        default="[]",
        description=(
            "JSON array of MCP server configurations. Each server should have: "
            "name, command, args (list), env (dict), enabled (bool). "
            "Example: [{\"name\": \"filesystem\", \"command\": \"npx\", "
            "\"args\": [\"-y\", \"@anthropic/mcp-filesystem\", \"/tmp\"], "
            "\"enabled\": true}]"
        ),
        group="servers",
    ),
]
