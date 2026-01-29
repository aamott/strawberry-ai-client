# MCP Wrapper (Quick Reference)

This folder contains Strawberry’s **MCP (Model Context Protocol) wrapper**, which makes MCP servers look like Strawberry “skills” to the rest of the app.

The core idea:

- MCP **server** → presented as a **skill class** (e.g. `HomeAssistantMCP`)
- MCP **tool** → presented as a **skill method** (e.g. `HomeAssistantMCP.turn_on_light(...)`)

This allows the LLM to call MCP capabilities using the same overall “skill” abstraction used for normal Python skills.

## Where this plugs in

- `strawberry.skills.service.SkillService.load_skills_async()` loads Python skills via `SkillLoader` and MCP skills via `MCPRegistry`, then merges them into a single list of `SkillInfo`.
- `strawberry.spoke_core.app.SpokeCore` registers an MCP settings namespace (placeholder) so the settings UI has an MCP section.

## Architecture (at a glance)

```
SkillService
  ├─ SkillLoader (Python skills)
  └─ MCPRegistry (MCP servers)
        ├─ MCPClient (one per server)
        └─ MCPSkillAdapter (MCP → SkillInfo)
```

## Files you’ll likely edit

- `mcp-design.md`
  - The detailed design doc (read this first when changing the MCP interface).

- `config.py`
  - `MCPServerConfig` dataclass.
  - Naming convention lives here via `get_skill_class_name()`.

- `client.py`
  - `MCPClient`: wraps the official Python `mcp` SDK.
  - Responsibilities:
    - start/stop server subprocess (stdio)
    - `initialize()` handshake
    - `list_tools()` caching
    - `call_tool()` execution

- `adapter.py`
  - `MCPSkillAdapter`: converts MCP tools to Strawberry `SkillInfo`/`SkillMethod`.
  - **This is the main modularity point**: if we change how the LLM “sees” skills (e.g. TypeScript interface), we should mostly change this file.

- `registry.py`
  - `MCPRegistry`: manages multiple MCP servers.
  - Start/stop all servers, return aggregated `SkillInfo` list, route tool calls.

- `settings.py`
  - Loads configs from `config/mcp.json`.
  - Also includes `parse_mcp_config()` and `save_mcp_configs()` helpers.

- `settings_schema.py`
  - Placeholder `MCP_SETTINGS_SCHEMA` so MCP shows up in the settings UI.
  - **Note**: today, MCP server lists are *not* edited via the SettingsManager.

## Configuration

MCP servers are configured in `ai-pc-spoke/config/mcp.json`.

Format:

```json
{
  "mcpServers": {
    "home_assistant": {
      "command": "npx",
      "args": ["-y", "@home-assistant/mcp-server"],
      "env": {
        "HASS_TOKEN": "${HASS_TOKEN}"
      },
      "enabled": true
    }
  }
}
```

Notes:

- `env` supports `${VAR}` expansion from the Spoke process environment.
- `enabled: false` keeps the config but skips startup.

## Usage patterns

### Start all configured MCP servers

```python
from strawberry.mcp import MCPRegistry, load_mcp_configs_from_settings

configs = load_mcp_configs_from_settings()
registry = MCPRegistry(configs)

await registry.start_all()
```

### Expose MCP servers as skills

```python
mcp_skills = registry.get_all_skills()  # List[SkillInfo]
```

Each running server becomes a `SkillInfo` whose `name` looks like `HomeAssistantMCP`.

### Call a tool by server name

```python
result = await registry.call_tool(
    server_name="home_assistant",
    tool_name="turn_on_light",
    arguments={"entity_id": "light.kitchen"},
)
```

### Call a tool by skill name (used for skill-style routing)

```python
result = await registry.call_tool_by_skill(
    skill_name="HomeAssistantMCP",
    method_name="turn_on_light",
    arguments={"entity_id": "light.kitchen"},
)
```

### Shutdown

```python
await registry.stop_all()
```

## How to extend / change safely

- If you want MCP tools to look different to the LLM (ex: TypeScript classes):
  - Start by changing `adapter.py`.
  - Keep `MCPClient` and `MCPRegistry` stable.

- If you want to support non-stdio transports (ex: SSE):
  - Add fields to `MCPServerConfig`.
  - Extend `MCPClient.start()` to select transport.

- If you want MCP settings to be editable in the Settings UI:
  - Upgrade SettingsManager to support dynamic lists.
  - Move server list config out of `config/mcp.json` into SettingsManager.

## Tests

- `tests/test_mcp.py` covers:
  - config parsing
  - signature generation
  - registry basics
  - client result extraction helpers

Run:

- `pytest -qq tests/test_mcp.py`
