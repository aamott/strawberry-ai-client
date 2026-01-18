# Strawberry AI - Spoke

Voice assistant spoke for the Strawberry AI platform.

## Quick Start

```bash
# Create and activate a shared repo venv (from repo root)
python3 -m venv .venv
source .venv/bin/activate

# Install core dependencies (terminal mode only)
pip install -e ai-pc-spoke

# Install with UI support (recommended for full experience)
pip install -e "ai-pc-spoke[ui]"

# Install with voice processing
pip install -e "ai-pc-spoke[picovoice,silero]"

# Install everything (all features)
pip install -e "ai-pc-spoke[all]"
```

## Configuration

1. **Environment Setup**: Copy `.env.example` to `.env` and fill in your API keys:
   ```bash
   cp .env.example .env
   ```
   Then edit `.env` with your actual API keys and settings.

2. **Device Configuration**: Edit `config/config.yaml` for device-specific settings like device name, skills path, etc. and `config/tensorzero.toml` for LLM configuration.

## Running

### CLI Mode (Text Interface)
The new SpokeCore-based CLI supports text chat and voice commands.

```bash
# Run CLI
strawberry-cli
# Or via python
python -m strawberry.ui.cli.main
```
**Voice in CLI:** Type `/voice` to toggle voice mode (requires voice dependencies).

### GUI Mode (Qt Interface)
The full graphical interface with chat bubble, history, and voice controls.

```bash
# Run GUI
strawberry-gui
# Or via python
python -m strawberry.ui.qt.app
```
**Voice in GUI:** Click the microphone icon to toggle voice listening.

### Legacy Terminal Mode
The classic terminal application (not based on SpokeCore).

```bash
# Run classic terminal
strawberry
# Run with voice enabled immediately
strawberry --voice
```

## Running Tests
```bash
strawberry-test
# Or via python
python -m pytest
```

## TODO (Backend Selection + UI Docs)

The Spoke codebase is designed to support pluggable backends (audio / VAD / STT / TTS), but
the user-facing selection/wiring is not complete yet.

- **Backend selection wiring**
  - **Audio input**: wire `settings.audio.backend` to instantiate `sounddevice` vs `pvrecorder` (pvrecorder backend not implemented yet)
  - **VAD**: wire `settings.vad.backend` (`silero` vs `cobra`) (cobra backend not implemented yet)
  - **STT**: wire `settings.stt.backend` (`leopard` vs `google`) (google backend not implemented yet)
  - **TTS**: wire `settings.tts.backend` (`orca` vs `google`) (google backend not implemented yet)
- **Config validation**
  - Fail fast with a clear error if the selected backend requires optional deps that aren’t installed
  - Keep `pip install -e ".[picovoice,google,silero,ui]"` as the recommended “full features” path
- **UI docs**
  - UI changes frequently; treat `ai-pc-spoke/src/strawberry/ui/` as the source of truth


### 


## Linting (Ruff)

If you use a virtual environment (recommended), run Ruff through the venv's Python
to avoid PATH / permission issues:

```bash
# Apply auto-fixes
../.venv/bin/python -m ruff check --fix .

# Verify lint is clean
../.venv/bin/python -m ruff check .
```

And run tests from the same venv:

```bash
../.venv/bin/python -m strawberry.testing.runner
```

**Note:** If you encounter `ModuleNotFoundError: No module named 'PySide6'`, you need to install the UI dependencies:
```bash
pip install -e ".[ui]"
```

## Project Structure

```
ai-pc-spoke/
├── src/strawberry/     # Main package
│   ├── audio/          # Audio I/O
│   ├── wake/           # Wake word detection
│   ├── vad/            # Voice activity detection
│   ├── stt/            # Speech-to-text
│   ├── tts/            # Text-to-speech
│   ├── ui/             # User interface (requires PySide6)
│   ├── pipeline/       # Conversation orchestration
│   └── config/         # Configuration management
├── config/             # Config files
├── skills/             # User skill files
└── tests/              # Test suite
```

## Troubleshooting

### Missing PySide6 Module

If you see `ModuleNotFoundError: No module named 'PySide6'`, it means you're trying to use UI functionality without installing the UI dependencies.

**Solution:** Install the UI dependencies:
```bash
pip install -e ".[ui]"
```

### Common Installation Options

- **Terminal only**: `pip install -e .` (no UI, no voice)
- **Terminal + UI**: `pip install -e ".[ui]"` (recommended)
- **Terminal + Voice**: `pip install -e ".[picovoice]"`
- **Full installation**: `pip install -e ".[all]"` (everything)



# TODO

- [ ] Add more skills
- [ ] Make it load the same config and .env regardless of where the command is run from (eg. running python -m strawberry-gui from the ai-hub directory should still read the config from ai-pc-spoke/config/config.yaml)
- [ ] Test deleting the config and loading from scratch (automatically recreate config.yaml and .env)
- [ ] Make all settings accessible from the settings menu, make it easier to configure tensorzero models, fallback models, and API keys.
- [ ] Make settings for custom wake words, VAD, STT, and TTS auto-populate with available options when the class is initialized. That way a user can add a custom wake word, VAD, STT, or TTS model and it will be detected, added to the list, and any API keys will be accessible from the settings menu. 