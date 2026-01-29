
---
description: Implementation plan for a TypeScript-facing Skills/MCP wrapper (LLM sees TypeScript classes; runtime remains Python)
---

# TypeScript Skills + MCP Wrapper (Implementation Plan)

This document is an implementation plan for a **TypeScript-facing wrapper** for Strawberry’s skills and MCP tools.

Intent: the LLM will be guided to *think* it is calling **TypeScript classes / methods**, while execution continues to happen through Strawberry’s existing Python runtime:

- Python repo skills (per `docs/SKILLS.md`)
- MCP servers via the Python `mcp` SDK (`strawberry.mcp.*`)
- Tool execution via `python_exec` (at least for v1)

The plan is optimized to be **simple**, **modular**, and **reversible**.

## Why do this?

- TypeScript-style call surfaces are often easier for an LLM to use consistently (camelCase, explicit object models).
- We may eventually want the LLM to produce TypeScript (or a TS-like DSL) regardless of where the skills are authored.
- We can get 80% of the benefit by only changing the *presentation layer* (prompt + mapping) while leaving execution unchanged.

## Non-goals (v1)

- Running arbitrary TypeScript code in production (`typescript_exec`). That is a later milestone.
- Changing how skills are written (they remain Python).
- Replacing the sandbox/gatekeeper enforcement model.

## Current State (Baseline)

Today, the model calls skills by generating Python executed through `python_exec`:

- Offline: `device.<SkillName>.<method>(...)`
- Online: `devices.<device_name>.<SkillName>.<method>(...)`

MCP servers already integrate as “skills” by being adapted into `SkillInfo` objects and routed by the gatekeeper.

## Proposed End State

We introduce a new TypeScript-facing surface:

- Offline: `ts_device.<SkillName>.<camelMethod>(...)`
- Online: `ts_devices.<camelDevice>.<SkillName>.<camelMethod>(...)`

And keep the runtime execution path:

- `ts_*` objects are Python proxies that route to the underlying `device`/`devices` objects.
- Gatekeeper continues to validate the final resolved target skill and method.

## Two Possible Strategies

### Strategy A (Recommended): TS-shaped API, Python runtime

This strategy changes the interface the LLM sees, but still executes Python.

- Provide `ts_device` and `ts_devices` in the `python_exec` globals.
- Provide TS-style names and signatures in prompts.

This is the smallest and safest change.

### Strategy B (Later): Real TypeScript execution

This strategy adds a new tool like `typescript_exec(code: string)` and runs the TS code inside a JS runtime (Deno recommended). TS code calls into Python via a JSON/RPC bridge.

Strategy A is a prerequisite: we want stable naming + call semantics first.

## The “Modularity Point”

To make switching easy, we separate:

1. **Presentation**: how skills are described to the LLM (signatures, docs, casing)
2. **Execution**: how calls are actually performed (existing Python sandbox/gatekeeper)

Concretely:

- Keep `SkillInfo/SkillMethod` as the internal truth
- Add a new **Presentation Adapter** that renders TS-like signatures + docs
- Add runtime proxies that map TS naming conventions to the existing underlying callables

If we later decide to make the LLM “see” TypeScript classes (even more strongly) or to actually execute TypeScript, only the presentation adapter + runtime needs to change.

## Naming + Mapping Rules

### Class names (skills)

Keep class names exactly as today:

- `WeatherSkill`, `CalculatorSkill`, ...
- MCP server skill names: `HomeAssistantMCP`, `Context7MCP`, ...

This avoids breaking existing behavior and avoids collisions.

### Method names

Expose **camelCase** method names to the LLM, map to Python `snake_case`.

Examples:

- `get_current_weather` → `getCurrentWeather`
- `set_volume` → `setVolume`

Rules:

- Do not expose methods that start with `_`.
- Best-effort acronym handling: `get_url` → `getUrl`.
- If a Python method is already camelCase (rare), keep it as-is.

### Device names (remote)

Today, device names are normalized as Python identifiers (e.g. `living_room_pc`).

For TS-facing calls, we should support BOTH:

- `ts_devices.living_room_pc` (backward compatible)
- `ts_devices.livingRoomPc` (preferred)

### Parameters

For v1, keep the same call style as Python: keyword arguments.

- `ts_device.CalculatorSkill.add(a=1, b=2)`

We do NOT require the model to pass an object literal.

Later we can optionally support:

- `ts_device.CalculatorSkill.add({ a: 1, b: 2 })`

### Types

Type mappings are best-effort for documentation only:

- `str` → `string`
- `int`/`float` → `number`
- `bool` → `boolean`
- `dict`/`Dict[...]` → `Record<string, unknown>`
- `list`/`List[...]` → `Array<unknown>`
- unknown / missing annotations → `unknown`

For MCP tools, infer from JSON Schema’s `type` field where possible.

## Where this Hooks into the Code

We need two integration points:

1. **Prompt rendering**: produce a TS-style “API surface” in the system prompt.
2. **python_exec runtime globals**: inject `ts_device` / `ts_devices` as proxies.

### Prompt rendering

We should add a setting that selects presentation language:

- `skills.presentation_language`: `python` | `typescript`

When set to `typescript`, `SkillService` should:

- Render methods in camelCase
- Use TS-ish type names in signatures
- Show examples using `ts_device` / `ts_devices`

### Runtime globals injection

Wherever the sandbox constructs the globals passed to code execution, add:

- `ts_device = TypeScriptDeviceProxy(device)`
- `ts_devices = TypeScriptDevicesProxy(devices)` (or reuse a unified proxy)

This should happen inside the sandbox executor so it works in both offline and online flows.

## Proposed New Modules

Recommended package layout (keeps MCP runtime separate from presentation):

- `strawberry/presentation/typescript/naming.py`
  - `snake_to_camel`, `camel_to_snake`, `device_name_to_camel`
- `strawberry/presentation/typescript/types.py`
  - Python-to-TS type mapping helpers
- `strawberry/presentation/typescript/prompt.py`
  - Render skill list as TS declarations or flattened method list
- `strawberry/presentation/typescript/proxy.py`
  - `TypeScriptDeviceProxy`, `TypeScriptSkillProxy`, `TypeScriptDevicesProxy`

These modules should have thorough docstrings and logging.

## Runtime Proxy Design

### `TypeScriptDeviceProxy`

Represents a device-like object (either local `device` or remote `devices.<name>`).

Responsibilities:

- On attribute access:
  - If attribute matches a skill class name: return a `TypeScriptSkillProxy`
  - Else: raise `AttributeError` with suggestions

### `TypeScriptDevicesProxy`

Represents the `devices` container in remote mode.

Responsibilities:

- On attribute access:
  - If attribute matches an underlying device name exactly (`living_room_pc`): return `TypeScriptDeviceProxy(underlying_device)`
  - If attribute is camelCase (`livingRoomPc`): map to snake_case device name and then return proxy
  - Else: raise `AttributeError` with suggestions

### `TypeScriptSkillProxy`

Represents a single skill class.

Responsibilities:

- On attribute access of a method name:
  - Map camelCase to snake_case
  - Validate method is public and exists
  - Return a callable wrapper that calls the underlying method

### Sync vs async

Underlying skill callables may be sync or async depending on how the sandbox is implemented.

Implementation rule:

- If the underlying callable returns an awaitable, return it as-is (caller can `await` if needed).
- Otherwise return the immediate result.

### Logging

Log mappings at `DEBUG`:

- `WeatherSkill.getCurrentWeather -> WeatherSkill.get_current_weather`

Avoid logging sensitive argument values.

## Prompt Format Options

We need to give the LLM a clear TS-style interface.

### Option A: Flat list (simplest)

- `WeatherSkill.getCurrentWeather(location: string): unknown`
- `CalculatorSkill.add(a: number, b: number): number`

### Option B: TS declarations (more “TS-feeling”)

```ts
declare const ts_device: {
  WeatherSkill: {
    /** Get current weather for a location. */
    getCurrentWeather(location: string): unknown
  }
}
```

V1 recommendation: **Option A** (flat list) because it’s easier to generate and less likely to confuse the model.

## Step-by-step Implementation Plan

### Step 1: Add naming utilities

Implement:

- `snake_to_camel(s: str) -> str`
- `camel_to_snake(s: str) -> str`

Add tests for edge cases:

- `get_url` ↔ `getUrl`
- `getHTTPServer` (best-effort; acceptable to become `get_http_server`)

### Step 2: Add TS type mapping helpers

Implement:

- `python_type_to_ts(annotation: Any) -> str`
- `json_schema_to_ts(schema: dict) -> str`

Keep it best-effort; return `unknown` when unsure.

### Step 3: Implement runtime proxies

Implement `TypeScriptDevicesProxy`, `TypeScriptDeviceProxy`, and `TypeScriptSkillProxy`.

Add tests:

- Resolves `ts_device.CalculatorSkill.add` to underlying `add`
- Resolves `ts_devices.livingRoomPc` → `devices.living_room_pc`
- Unknown method produces readable error

### Step 4: Inject TS proxies into sandbox globals

In the sandbox executor, add:

- `ts_device`
- `ts_devices`

And confirm gatekeeper enforcement still applies.

### Step 5: Add TS prompt renderer

Add a renderer that takes `List[SkillInfo]` and produces TS-ish signatures.

### Step 6: Add a settings flag

Add `skills.presentation_language` and switch the SkillService prompt accordingly.

### Step 7: E2E verification

Run a simple `python_exec` code path that uses TS proxies:

```python
print(ts_device.CalculatorSkill.add(a=1, b=2))
```

And in remote mode (when available):

```python
print(ts_devices.livingRoomPc.MediaControlSkill.setVolume(level=20))
```

## Test Plan

### Unit tests

- Naming conversion
- Type mapping conversion
- Proxy routing
- Error messages include helpful suggestions

### Integration tests

- Ensure `ts_device` and `ts_devices` exist in sandbox globals
- Ensure calling via TS proxies triggers the same gatekeeper restrictions

## Rollout Plan

- **Phase 1**: ship proxies (hidden), keep python prompt
- **Phase 2**: add TS prompt behind setting
- **Phase 3**: optional default to TS prompt for new installs

## Future Plan: Real TypeScript Execution (Strategy B)

When ready:

- Add a new tool: `typescript_exec(code: str)`
- Use Deno to run TypeScript
- Provide an RPC bridge to the Python gatekeeper

Strategy A keeps the naming/prompt stable so the transition is primarily a change in execution engine.

