---
description: SpokeCore class design summary
---
# SpokeCore


## Purpose

`strawberry.spoke_core.SpokeCore` is the **single backend entrypoint** that UIs (Qt/CLI/voice interface) import and drive. It owns the chat/agent loop and skill/tool execution, and provides an event stream for UI rendering.

It must contain **no UI/frontend code**. UIs subscribe to events and call methods; they do not embed backend logic.

## Folder structure

`ai-pc-spoke/src/strawberry/spoke_core/`

- **`app.py`**: `SpokeCore` implementation (lifecycle, sessions, agent loop, event emission)
- **`events.py`**: typed core events for UIs (`CoreReady`, `CoreError`, `MessageAdded`, `ToolCallStarted`, `ToolCallResult`, `SettingsChanged`)
- **`session.py`**: `ChatSession` state (messages + busy flag)
- **`settings_schema.py`**: declarative settings schema for UIs to render (shared across UIs)

## Responsibilities

- **AI communication**
  - Local AI mode
  - Hub AI mode
  - Streaming tool-call visibility via events
- **Skill management**
  - Load skills from the configured skills folder
  - Provide a tool execution surface for the agent loop (native tool calls + legacy fenced-code fallback)
  - (When online) register skills with the hub and maintain heartbeats
- **Settings + Hub auth ownership**
  - Import settings internally via `strawberry.config.get_settings()`
  - Own hub connection details (URL/token) from settings rather than requiring each UI to pass them in

## What external code (UIs) use

- **Lifecycle**: `await core.start()`, `await core.stop()`
- **Sessions**: `session = core.new_session()`, `core.get_session(session_id)`
- **Chat**: `await core.send_message(session_id, text)`
- **Events**:
  - Callback subscription: `core.subscribe(handler)`
  - Async iteration: `async for event in core.events(): ...`

UIs should treat `SpokeCore` as authoritative for:

- session state
- agent loop progression
- tool execution and results

## Current status vs intended design

- **No frontend/UI dependencies**: ✅ `spoke_core/` imports config/llm/skills/hub only - no UI code.
- **Local vs Hub AI mode**: ✅ Implemented.
  - `SpokeCore.is_online()` returns actual hub connection state.
  - `await core.connect_hub()` connects to hub using settings.
  - `await core.disconnect_hub()` disconnects.
  - Mode changes emit `ModeChanged` events.
- **Hub skill registration**: ✅ Wired in `SpokeCore`.
  - `connect_hub()` automatically registers skills and starts heartbeat.
  - Skills callback is set up for Hub → Spoke skill execution.
- **Settings path override**: ⚠️ `SpokeCore.__init__(settings_path=...)` exists but is currently unused (settings are loaded via `get_settings()`).
