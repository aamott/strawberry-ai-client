---
description: SettingsManager reference. Start here when working with settings.
---

# SettingsManager

The `SettingsManager` is a centralized settings service with namespace isolation.
Each module (SpokeCore, VoiceCore, individual backends, etc.) registers its own
namespace and schema. The Settings UI reads those schemas to build forms dynamically.

**Location**: `ai-pc-spoke/src/strawberry/shared/settings/`

## Architecture

```
┌──────────────────┐   register()    ┌──────────────────┐
│  SpokeCore       │───────────────▶│                  │
│  VoiceCore       │   get/set()    │  SettingsManager  │──▶ config.yaml
│  Backends        │◀──────────────▶│                  │──▶ .env (secrets)
│  Skills          │   on_change()  │                  │
└──────────────────┘                └──────────────────┘
                                            ▲
                                            │ queries schemas
                                    ┌───────┴────────┐
                                    │  Settings UI    │
                                    │  (Qt / CLI)     │
                                    └────────────────┘
```

### Key modules

| File | Purpose |
|------|---------|
| `manager.py` | Core SettingsManager class — registration, get/set, events, persistence |
| `schema.py` | `FieldType` enum, `SettingField` dataclass, validation helpers |
| `storage.py` | YAML and .env persistence backends |
| `view_model.py` | `SettingsViewModel` — presentation layer for UI consumption |

## Quick Start

```python
from strawberry.shared.settings import SettingsManager, SettingField, FieldType

# 1. Initialize (once at app startup)
settings = SettingsManager(config_dir=Path("config"))

# 2. Define a schema
schema = [
    SettingField(key="hub.url", label="Hub URL", type=FieldType.TEXT, default="http://localhost:8000"),
    SettingField(key="api_key", label="API Key", type=FieldType.PASSWORD, secret=True, env_key="HUB_API_KEY"),
    SettingField(key="backends", label="Active Backends", type=FieldType.LIST),
]

# 3. Register a namespace
settings.register("my_module", "My Module", schema, tab="General", order=10)

# 4. Get / set values
url = settings.get("my_module", "hub.url")
settings.set("my_module", "hub.url", "http://example.com")

# 5. React to changes
settings.on_change(lambda ns, key, value: print(f"{ns}.{key} = {value}"))

# 6. Register external validation (optional)
settings.register_validator("my_module", "backends", lambda v: "Legacy deprecated" if "legacy" in v else None)
```

## Namespace Registration

```python
settings.register(
    namespace="voice_core",        # Unique ID
    display_name="Voice",          # Shown in UI
    schema=VOICE_CORE_SCHEMA,      # List[SettingField]
    order=20,                      # Sort priority (lower = first)
    tab="Voice",                   # UI tab grouping
)
```

- **namespace**: Unique string identifier. Conventions: `spoke_core`, `voice_core`, `voice.stt.leopard`.
- **tab**: Groups namespaces into UI tabs. Tab sort order is derived from the minimum `order` value of namespaces within that tab — no hardcoded list.
- **order**: Controls sort order within a tab and determines tab ordering.

## Field Types

| FieldType | Widget | Notes |
|-----------|--------|-------|
| `TEXT` | Text input | |
| `PASSWORD` | Masked input | Use `secret=True`, stored in `.env` |
| `NUMBER` | Numeric input | Supports `min_value`, `max_value` |
| `CHECKBOX` | Toggle | Boolean |
| `SELECT` | Dropdown | Requires `options` list |
| `DYNAMIC_SELECT` | Dropdown | Populated at runtime via `options_provider` |
| `PROVIDER_SELECT` | Dropdown + sub-settings | Controls which backend namespace to show |
| `LIST` | Ordered list editor | Supports reordering, add/remove |
| `ACTION` | Button | Triggers callback via `action` |
| `MULTILINE` | Textarea | |
| `FILE_PATH` | Path + browse button | `metadata={"must_exist": True}` |
| `DIRECTORY_PATH` | Path + browse button | `metadata={"create_if_missing": True}` |
| `COLOR` | Color picker | Hex format `#RRGGBB` |
| `SLIDER` | Range slider | `min_value=0.0, max_value=1.0` |
| `DATE` | Date picker | ISO format |
| `TIME` | Time picker | HH:MM format |
| `DATETIME` | Date+time picker | `metadata={"calendar_popup": True}` |

## Persistence

- **Non-secrets** → `config/config.yaml` (line-preserving YAML updates)
- **Secrets** → `.env` file (preserves comments and unknown keys)
- On save, values are written to both files and applied immediately to `os.environ`.

## Validation

- **Schema validation**: `SettingField.validate(value)` checks types, ranges, required options.
- **External validators**: `settings.register_validator(namespace, key, callback)` for cross-field or system-state checks.
- **Validation modes**: `ON_CHANGE`, `ON_BLUR`, `ON_SAVE`, `ASYNC` (per-field via `validation_mode`).

## Settings UI

The UI is a **consumer** that:
- Queries `settings.get_namespaces()` to discover registered schemas.
- Groups namespaces by `tab` attribute and sorts by `order`.
- Renders fields using `FieldType` to select widgets.
- Handles `PROVIDER_SELECT` via the **Template Pattern**: `provider_namespace_template` (e.g. `"voice.stt.{value}"`) dynamically shows sub-settings for the selected backend.

### Implementations
- **Qt** (GUI V2): `ai-pc-spoke/src/strawberry/ui/gui_v2/components/settings_window.py`
- **CLI**: `ai-pc-spoke/src/strawberry/ui/cli/settings_menu.py`

## Design Principles

1. **Decoupling**: The UI uses templates and schemas, never hardcodes module names.
2. **Modularity**: Each module owns its schema and can be added/removed independently.
3. **Namespace isolation**: Modules can't accidentally overwrite each other's settings.
4. **Secrets handling**: API keys and tokens stored separately in `.env`.
5. **Discovery**: Provider backends self-describe their settings via `get_settings_schema()`.
6. **Reactive**: `on_change()` callbacks allow modules to react immediately to setting changes.
