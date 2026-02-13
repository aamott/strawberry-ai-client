# Strawberry AI - Spoke

Voice assistant spoke/client for the Strawberry AI platform. For the hub, see [ai-hub](../ai-hub/README.md).

## Quick Start

```bash
# From the repo root
python3 -m venv .venv
source .venv/bin/activate

# Install options (choose one)
pip install -e "ai-pc-spoke"           # CLI only
pip install -e "ai-pc-spoke[ui]"        # CLI + GUI (recommended)
pip install -e "ai-pc-spoke[picovoice,silero]"  # CLI + voice
pip install -e "ai-pc-spoke[all]"       # Everything
```

## Configuration

1. **Environment setup**: Copy `.env.example` to `.env` and fill in your API keys:
   ```bash
   cp .env.example .env
   ```
   Then edit `.env` with your actual API keys and settings.

2. **Device configuration**: Edit `config/settings.yaml` for device-specific settings (device name, skills path, etc.) and `config/tensorzero.toml` for LLM configuration.

## Running

### CLI
The unified CLI supports interactive chat, one-shot messages, settings, and developer tools.

```bash
strawberry-cli                          # Interactive chat (default)
strawberry-cli "What time is it?"       # One-shot message
strawberry-cli --settings               # Settings menu
strawberry-cli skill-tester             # Skill interaction tester
```
**Voice in CLI:** Type `/voice` to toggle voice mode.

### GUI UI
The full graphical interface with chat history and voice controls.

```bash
# Run GUI
strawberry-gui
# Or via python
python -m strawberry.ui.gui_v2
```
**Voice in GUI:** Click the microphone icon to toggle voice listening.

### Settings CLI
Manage settings from the command line without launching a full UI.

```bash
strawberry-cli --settings list
strawberry-cli --settings show voice_core
strawberry-cli --settings get voice_core stt.backend
strawberry-cli --settings set voice_core stt.backend whisper
strawberry-cli --settings apply
strawberry-cli --settings edit voice_core stt.order
strawberry-cli --settings reset voice_core stt.backend
```


### Tests
```bash
strawberry-test -h  # See how to use the test command
# Or via python
python -m pytest
```

## Core Components
- **SpokeCore**: Handles chat, skills, hub communication, and agent orchestration.
- **VoiceCore**: Runs the voice pipelines (listening pipeline and speaking pipeline).
- **UI**: CLI/GUI frontends that interact with SpokeCore and/or VoiceCore.
- **VoiceInterface**: Voice-only example UI that wires VoiceCore and SpokeCore together (in `ui/voice_interface/`).
- **SettingsManager**: Centralized configuration with namespace isolation, schema-driven validation, and reactive updates (see [SETTINGS.md](../docs/plans/settings/SETTINGS.md)).

## Project Structure
```
ai-pc-spoke/
├── src/strawberry/         # Main package
│   ├── spoke_core/          # SpokeCore - LLM, chat, and skill services
│   ├── ui/                 # User interfaces
│   │   ├── qt/             # Qt-based GUI
│   │   ├── cli/            # Unified CLI (chat, settings, tools)
│   │   └── voice_interface/  # Voice-only interface (example)
│   ├── voice/              # Voice processing
│   │   ├── stt/            # Speech-to-text (Leopard, etc.)
│   │   ├── tts/            # Text-to-speech (Orca, Pocket, etc.)
│   │   ├── vad/            # Voice activity detection (Silero)
│   │   ├── wakeword/       # Wake word detection (Porcupine)
│   │   ├── audio/          # Audio I/O and playback
│   │   ├── pipeline/       # Conversation orchestration
│   │   ├── controller.py   # VoiceController (VoiceCore)
│   │   └── state.py        # Voice state machine
│   ├── shared/settings/    # SettingsManager, schema, storage
│   ├── skills/             # Skill loading and sandbox execution
│   └── hub/                # Hub client for remote ops
├── config/                 # Config files (settings.yaml, tensorzero.toml)
├── skills/                 # User skill files
└── tests/                  # Test suite
```


## Common Installation Options

- **CLI only**: `pip install -e "ai-pc-spoke"` (no UI, no voice)
- **CLI + GUI**: `pip install -e "ai-pc-spoke[ui]"` (recommended)
- **CLI + Voice**: `pip install -e "ai-pc-spoke[picovoice,silero]"`
- **Everything**: `pip install -e "ai-pc-spoke[all]"`



# Notes

- Validate config/.env regeneration flows (create examples only; never ship secrets).
- Ensure system prompt is configurable via settings (`settings_schema.py`).
- Confirm skills re-register after brief Hub disconnects.
- Allow user-provided MCP tool descriptions in `mcp_config.json`.