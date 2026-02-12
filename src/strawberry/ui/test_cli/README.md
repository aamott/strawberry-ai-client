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

### Interactive TUI

```bash
# Browse tabs → namespaces → fields, edit values, apply
python -m strawberry.ui.test_cli --settings interactive
```

Notes:

- The settings loader resolves the skills directory from `spoke_core.skills.path` (default `skills/`).
- Config directory defaults to `config/` at repo root; override with `--config /path/to/config`.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error |
| 2 | Timeout |
| 3 | Config error |

See [TEST_CLI_DESIGN.md](./TEST_CLI_DESIGN.md) for full documentation.
