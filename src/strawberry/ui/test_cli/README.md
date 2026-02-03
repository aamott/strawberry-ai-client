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
| `--offline` | Skip hub, force local mode |
| `--show-logs` | Display debug logs |
| `--timeout N` | Set timeout (default: 120s) |

## Interactive Commands

- `/quit`, `/q`, `/exit` — Exit the CLI

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error |
| 2 | Timeout |
| 3 | Config error |

See [TEST_CLI_DESIGN.md](./TEST_CLI_DESIGN.md) for full documentation.
