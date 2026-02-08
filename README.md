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

### CLI UI
The SpokeCore-based CLI supports text chat and voice commands.

```bash
# Run CLI
strawberry-cli
# Or via python
python -m strawberry.ui.cli.main
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
# List all namespaces
python -m strawberry.ui.test_cli --settings list

# Show a namespace with all fields
python -m strawberry.ui.test_cli --settings show voice_core

# Get/set individual values
python -m strawberry.ui.test_cli --settings get voice_core stt.backend
python -m strawberry.ui.test_cli --settings set voice_core stt.backend whisper

# Apply pending changes (required after set)
python -m strawberry.ui.test_cli --settings apply

# Interactive list editor for backends
python -m strawberry.ui.test_cli --settings edit voice_core stt.order

# Reset a field to default
python -m strawberry.ui.test_cli --settings reset voice_core stt.backend
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
│   │   ├── cli/            # CLI-based UI
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



# TODO

- [ ] Add more skills
- [ ] Test deleting the config and loading from scratch (automatically recreate config.yaml and .env)
- [x] Make a unified settings GUI, make it easier to configure tensorzero models, fallback models, and API keys.
- [ ] Move `SYSTEM_PROMPT_TEMPLATE` from service.py to config.yaml (with fallback).