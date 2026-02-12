---
description: How to use the test CLI (a live chat interface for testing and debugging).
---
# Test CLI

A simplified CLI for automated testing and debugging of Strawberry Spoke.

## Quick Start

```bash
cd ai-pc-spoke
source .venv/bin/activate

# Interactive mode
python -m strawberry.ui.test_cli

# One-shot message
python -m strawberry.ui.test_cli "What time is it?"

# JSON output (for testing)
python -m strawberry.ui.test_cli "What time is it?" --json

# Force offline mode
python -m strawberry.ui.test_cli "2+2?" --offline
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

- `/quit`, `/q`, `/exit` — Exit the CLI

## Settings CLI

The test CLI includes a lightweight settings browser/editor that registers the core schema and auto-discovers skill `SETTINGS_SCHEMA` without booting the full SpokeCore.

### Listing namespaces

```bash
# Show all namespaces grouped by tab (General, Skills, etc.)
python -m strawberry.ui.test_cli --settings list
```

### Viewing a namespace

```bash
# Pretty-print all fields with current values and descriptions
python -m strawberry.ui.test_cli --settings show skills.weather_skill
```

### Getting/setting values

```bash
# Read a single key
python -m strawberry.ui.test_cli --settings get skills.weather_skill units

# Buffer an update (applied on --settings apply)
python -m strawberry.ui.test_cli --settings set skills.weather_skill units imperial

# Apply buffered changes
python -m strawberry.ui.test_cli --settings apply
```

### Interactive Settings Menu

Launch the full interactive TUI with ANSI colors, breadcrumb navigation,
type-specific field editors, search, and a pending-changes diff view:

```bash
# Either of these launches the interactive menu:
python -m strawberry.ui.test_cli --settings
python -m strawberry.ui.test_cli --settings interactive
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

See [TEST_CLI_DESIGN.md](./TEST_CLI_DESIGN.md) for full documentation.
