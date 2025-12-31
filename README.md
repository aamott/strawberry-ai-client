# Strawberry AI - Spoke

Voice assistant spoke for the Strawberry AI platform.

## Quick Start

```bash
# Install core dependencies
pip install -e .

# Install with voice processing
pip install -e ".[picovoice,silero]"

# Install everything
pip install -e ".[all]"
```

## Configuration

1. Copy `.env.example` to `.env` and fill in your API keys
2. Edit `config/config.yaml` for device settings

## Running

```bash
# Terminal mode
strawberry

# Run tests
strawberry-test
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
│   ├── pipeline/       # Conversation orchestration
│   └── config/         # Configuration management
├── config/             # Config files
├── skills/             # User skill files
└── tests/              # Test suite
```

