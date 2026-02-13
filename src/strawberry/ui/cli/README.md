---
description: How to use the Strawberry CLI (chat, settings, and developer tools).
---
# Strawberry CLI

Unified command-line interface for Strawberry Spoke — interactive chat, one-shot
messages, settings management, and developer tools.

## Quick Start

```bash
cd ai-pc-spoke
source .venv/bin/activate

# Interactive mode (default)
strawberry-cli

# One-shot message
strawberry-cli "What time is it?"

# JSON output (for testing/scripting)
strawberry-cli "What time is it?" --json

# Force offline mode
strawberry-cli "2+2?" --offline

# Skill interaction tester
strawberry-cli skill-tester
```

## Key Flags

| Flag | Description |
|------|-------------|
| `-i, --interactive` | Run as REPL |
| `-j, --json` | Output JSON for parsing |
| `-q, --quiet` | Only print final response |
| `-c, --compact` | Truncate tool output for concise display |
| `--offline` | Skip hub, force local mode |
| `--show-logs` | Display debug logs |
| `--timeout N` | Set timeout (default: 120s) |
| `--settings ...` | Run settings subcommands (see below) |
| `--config PATH` | Override config directory (defaults to repo `config/`) |

## Interactive Commands

| Command | Description |
|---------|-------------|
| `/help`, `/h` | Show available commands |
| `/quit`, `/q` | Quit |
| `/voice` | Toggle voice mode |
| `/settings` | Open settings menu |
| `/status` | Show mode, model, voice status |
| `/connect` | Reconnect to Hub |
| `/clear` | Clear conversation |
| `/last` | Show last tool output |

## Settings CLI

Includes a lightweight settings browser/editor that registers the core schema and auto-discovers skill `SETTINGS_SCHEMA` without booting the full SpokeCore.

### Listing namespaces

```bash
strawberry-cli --settings list
```

### Viewing a namespace

```bash
strawberry-cli --settings show skills.weather_skill
```

### Getting/setting values

```bash
strawberry-cli --settings get skills.weather_skill units
strawberry-cli --settings set skills.weather_skill units imperial
strawberry-cli --settings apply
```

### Interactive Settings Menu

Launch the full interactive TUI with ANSI colors, breadcrumb navigation,
type-specific field editors, search, and a pending-changes diff view:

```bash
strawberry-cli --settings
strawberry-cli --settings interactive
```

**Navigation:**

| Key | Action |
|-----|--------|
| `N` | Select item by number |
| `b` / `back` | Go back one level |
| `h` / `help` | Show contextual help |
| `a` / `apply` | Apply pending changes (with diff preview) |
| `d` / `discard` | Discard pending changes |
| `p` / `pending` | Show pending changes diff |
| `s <query>` | Search fields across all namespaces |
| `r N` | Reset field N to default (in namespace view) |
| `q` / `quit` | Exit (prompts if changes pending) |

**Field type editors:**

Each of the 17 field types has a dedicated editor:

- **TEXT / MULTILINE** — inline text entry
- **PASSWORD** — masked input via `getpass`
- **NUMBER** — with min/max range validation
- **CHECKBOX** — single-key toggle
- **SELECT / DYNAMIC_SELECT** — numbered picker
- **SLIDER** — visual bar with step display
- **COLOR** — hex validation (`#RRGGBB`)
- **FILE_PATH / DIRECTORY_PATH** — tilde/var expansion, existence checks
- **DATE / TIME / DATETIME** — format-validated input
- **LIST / PROVIDER_SELECT** — sub-editor with add/remove/reorder
- **ACTION** — display-only (not editable from CLI)

**Notes:**

- The settings loader resolves the skills directory from `spoke_core.skills.path` (default `skills/`).
- Config directory defaults to `config/` at repo root; override with `--config /path/to/config`.
- Type badges like `[KEY]`, `[SEL]`, `[CHK]` appear next to each field for quick identification.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error |
| 2 | Timeout |
| 3 | Config error |

## Skill Interaction Tester

Launch the developer tool that lets you "be" the LLM:

```bash
strawberry-cli skill-tester
strawberry-cli skill-tester --skills-dir /path/to/skills
```

See the [Skill Interaction Tester guide](../../../../docs/Skill_Interaction_Tester.md) for details.

See [TEST_CLI_DESIGN.md](./TEST_CLI_DESIGN.md) for the original design spec.
