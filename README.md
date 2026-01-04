# Strawberry AI - Spoke

Voice assistant spoke for the Strawberry AI platform.

## Quick Start

```bash
# Install core dependencies (terminal mode only)
pip install -e .

# Install with UI support (recommended for full experience)
pip install -e ".[ui]"

# Install with voice processing
pip install -e ".[picovoice,silero]"

# Install everything (all features)
pip install -e ".[all]"
```

## Configuration

1. **Environment Setup**: Copy `.env.example` to `.env` and fill in your API keys:
   ```bash
   cp .env.example .env
   ```
   Then edit `.env` with your actual API keys and settings.

2. **Device Configuration**: Edit `config/config.yaml` for device-specific settings like device name, skills path, etc. and `config/tensorzero.toml` for LLM configuration.

## Running

```bash
# Terminal mode (no UI dependencies required)
strawberry

# GUI mode (requires UI dependencies: pip install -e ".[ui]")
strawberry-gui

# Run tests
strawberry-test
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

## Linting (Ruff)

If you use a virtual environment (recommended), run Ruff through the venv's Python
to avoid PATH / permission issues:

```bash
# Apply auto-fixes
.venv/bin/python -m ruff check --fix .

# Verify lint is clean
.venv/bin/python -m ruff check .
```

And run tests from the same venv:

```bash
.venv/bin/python -m strawberry.testing.runner
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

