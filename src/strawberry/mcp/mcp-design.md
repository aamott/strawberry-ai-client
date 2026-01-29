---
description: Design of the MCP-to-skill interface (the mcp wrapper). Refer to this whenever making edits to the MCP interface. 
---

# MCP Skill Wrapper

This module wraps MCP (Model Context Protocol) servers so they appear as Python skill classes to the LLM. Each MCP server becomes a "class" and each MCP tool becomes a "method".

**Reference**: See `docs/SKILLS.md` for skill conventions.

## Design Goals

1. **Unified Interface** - MCP tools appear identical to Python skills: `device.ServerNameMCP.tool_name()`
2. **Minimal Complexity** - Thin wrapper around the official `mcp` Python SDK
3. **Modular** - Easy to swap out the "how skills are presented" layer (Python → TypeScript interface)
4. **Async-first** - MCP is inherently async; we embrace that

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         SkillService                             │
│  Unified view: Python skills + MCP skills (as SkillInfo)         │
└───────────────────────────┬─────────────────────────────────────┘
                            │ get_all_skills() → List[SkillInfo]
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│  SkillLoader  │   │  MCPRegistry  │   │ (Future: TS)  │
│ Python skills │   │ MCP servers   │   │               │
└───────────────┘   └───────┬───────┘   └───────────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │MCPClient │  │MCPClient │  │MCPClient │
        │(server1) │  │(server2) │  │(server3) │
        └────┬─────┘  └──────────┘  └──────────┘
             │
             ▼
    ┌─────────────────┐
    │ MCPSkillAdapter │  Converts MCP Tool → SkillInfo/SkillMethod
    └─────────────────┘
```

## Module Breakdown

### `config.py` - Configuration
```python
@dataclass
class MCPServerConfig:
    name: str              # e.g., "home_assistant"
    command: str           # e.g., "npx"
    args: List[str]        # e.g., ["-y", "@home-assistant/mcp-server"]
    env: Dict[str, str]    # Environment variables for the process
    enabled: bool = True
```

### `client.py` - Single Server Connection
```python
class MCPClient:
    """Wraps MCP SDK for one server. Manages lifecycle + tool calls."""
    
    async def start() -> bool          # Start the server process
    async def stop() -> None           # Stop gracefully
    async def list_tools() -> List[Tool]  # Get available tools
    async def call_tool(name, args) -> Any  # Execute a tool
```

### `adapter.py` - MCP → Skill Conversion
```python
class MCPSkillAdapter:
    """Converts MCP tools to SkillInfo format.
    
    This is the MODULARITY POINT. If we switch to TypeScript skill 
    signatures, we only change this adapter.
    """
    
    def adapt_server(client: MCPClient) -> SkillInfo
    def adapt_tool(tool: Tool) -> SkillMethod
```

### `registry.py` - Multi-Server Manager
```python
class MCPRegistry:
    """Manages multiple MCPClient instances."""
    
    async def start_all() -> Dict[str, bool]
    async def stop_all() -> None
    def get_client(name: str) -> MCPClient
    def get_all_skills() -> List[SkillInfo]
```

### `settings.py` - Configuration Loading
```python
def load_mcp_configs_from_settings() -> List[MCPServerConfig]
```

## Sequence: Starting MCP Servers

```
SkillService.load_skills_async()
    │
    ├─► load_mcp_configs_from_settings()
    │       └─► Read from config/mcp.json (or settings.yaml in future)
    │
    ├─► MCPRegistry(configs)
    │
    └─► registry.start_all()
            │
            ├─► MCPClient(config1).start()
            │       └─► subprocess: npx -y @server/mcp ...
            │       └─► MCP handshake (initialize)
            │       └─► list_tools() → cache tools
            │
            └─► MCPClient(config2).start()
                    └─► ...
```

## Sequence: Executing an MCP Tool

```
LLM generates: device.HomeAssistantMCP.turn_on_light(entity_id="light.kitchen")
    │
    ▼
Gatekeeper.route_call("HomeAssistantMCP", "turn_on_light", {...})
    │
    ├─► Detect "MCP" suffix → route to MCPRegistry
    │
    ▼
MCPRegistry.call_tool("home_assistant", "turn_on_light", {...})
    │
    ▼
MCPClient.call_tool("turn_on_light", {"entity_id": "light.kitchen"})
    │
    ▼
MCP SDK → server process (stdio/SSE) → result
    │
    ▼
Return result to LLM
```

## Naming Convention

MCP servers get a `MCP` suffix to distinguish from Python skills:
- Server name: `home_assistant` → Skill class: `HomeAssistantMCP`
- Server name: `firebase` → Skill class: `FirebaseMCP`

## Configuration File (Temporary)

Until settings manager supports dynamic lists, MCP configs live in:
`config/mcp.json`

```json
{
  "mcpServers": {
    "home_assistant": {
      "command": "npx",
      "args": ["-y", "@home-assistant/mcp-server"],
      "env": {
        "HASS_TOKEN": "${HASS_TOKEN}"
      }
    }
  }
}
```

## TODO
- [x] Create design document
- [ ] Implement modules (config, client, adapter, registry, settings)
- [ ] Upgrade settings manager to handle dynamic lists (future)