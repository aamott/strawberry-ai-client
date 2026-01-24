---
description: CLI UI overview for the Spoke and todo items. 
---

# CLI UI (Spoke)

This document tracks the CLI implementation in the Spoke and links to the
planning/design doc.

## Implementation location

- Source: `ai-pc-spoke/src/strawberry/ui/cli/`
- Entrypoint: `strawberry-cli` → `strawberry.ui.cli.main:main`

## Design reference

- Plan: [`docs/plans/CLI-UI-Design.md`](../../../../../docs/plans/CLI-UI-Design.md)

## Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/quit`, `/q` | Quit the CLI |
| `/clear` | Clear conversation history |
| `/last` | Show full output of last tool call |
| `/voice` | Toggle voice mode |
| `/connect` | Connect to Hub |
| `/status` | Show connection status |
| `/settings` | Open interactive settings menu |

## Architecture

The CLI uses the same architecture as the Qt UI:

- **SettingsManager**: Centralized settings service (shared with Qt UI)
- **SpokeCore**: Chat and skill execution engine
- **VoiceCore**: Voice processing (STT/TTS/VAD/wake word)

Settings are persisted to:
- `config/settings.yaml` - General settings
- `.env` - Secrets (API keys, tokens)

## Notes

- Tool call expansion uses `Shift+Tab` with `/last` as a fallback.
- Voice mode uses the same VoiceCore as the Qt UI.
- Settings changes in CLI are immediately visible in Qt UI and vice versa.

## TODO

- [ ] Detect hub coming online/offline