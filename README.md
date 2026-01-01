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

2. **Device Configuration**: Edit `config/config.yaml` for device-specific settings like device name, skills path, etc.

## Running

```bash
# Terminal mode (no UI dependencies required)
strawberry

# GUI mode (requires UI dependencies: pip install -e ".[ui]")
strawberry-gui

# Run tests
strawberry-test
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

