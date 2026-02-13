# Test CLI Design

A simplified CLI interface for automated testing and scripting.

## Overview

`test_cli` is a separate module from the interactive CLI, designed for:
- **Automated testing** — Send a message, get structured output, check exit code
- **Scripting** — Invoke from shell/pytest with predictable behavior
- **Debugging** — Full tool call visibility, optional log passthrough

## Usage

```bash
# Single message (default: prints result, exits)
python -m strawberry.ui.test_cli "What is 2+2?"

# JSON output (for parsing in tests)
python -m strawberry.ui.test_cli "What is 2+2?" --json

# Interactive mode (for manual testing)
python -m strawberry.ui.test_cli --interactive

# Show TensorZero/Rust logs (default: filtered)
python -m strawberry.ui.test_cli "message" --show-logs

# Force offline mode (skip hub connection)
python -m strawberry.ui.test_cli "message" --offline

# Custom timeout (default: 120s)
python -m strawberry.ui.test_cli "message" --timeout 60

# Multiple messages in sequence
python -m strawberry.ui.test_cli "Hello" "What did I just say?"
```

## Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `messages` | positional | - | One or more messages to send |
| `--interactive`, `-i` | flag | false | Run interactive REPL instead of one-shot |
| `--json`, `-j` | flag | false | Output JSON instead of plain text |
| `--show-logs` | flag | false | Don't filter TensorZero/Rust stderr logs |
| `--offline` | flag | false | Skip hub connection, force local mode |
| `--timeout` | int | 120 | Timeout in seconds per message |
| `--config` | path | config/ | Config directory path |
| `--quiet`, `-q` | flag | false | Only print final assistant response |

## Output Format

### Plain Text (default)

```
[tool] search_skills(query="")
  -> {"skills": [...], "count": 5}

[tool] python_exec(code="print(device.TimeSkill.get_current_time())")
  -> 2024-01-15 14:32:00

[assistant]
The current time is 2:32 PM.
```

- **Full tool arguments** — No truncation (unlike interactive CLI's 40-char limit)
- **Full tool results** — Complete output for debugging
- **Clear section markers** — `[tool]`, `[assistant]`, `[error]`

### JSON Mode (`--json`)

```json
{
  "success": true,
  "messages": [
    {"role": "user", "content": "What time is it?"},
    {"role": "assistant", "content": "The current time is 2:32 PM."}
  ],
  "tool_calls": [
    {
      "name": "search_skills",
      "arguments": {"query": ""},
      "result": "{\"skills\": [...]}",
      "success": true
    },
    {
      "name": "python_exec", 
      "arguments": {"code": "print(device.TimeSkill.get_current_time())"},
      "result": "2024-01-15 14:32:00",
      "success": true
    }
  ],
  "duration_ms": 1523,
  "mode": "local"
}
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success — got assistant response |
| 1 | Error — SpokeCore error or tool failure |
| 2 | Timeout — no response within limit |
| 3 | Configuration error — missing config, bad args |

## Implementation

### File Structure

```
ai-pc-spoke/src/strawberry/ui/test_cli/
├── __init__.py
├── __main__.py      # Entry point (argparse + asyncio.run)
├── runner.py        # TestRunner class (wraps SpokeCore)
└── output.py        # Output formatters (plain, JSON)
```

### Key Classes

#### `TestRunner`

```python
class TestRunner:
    """Simplified SpokeCore wrapper for testing."""
    
    def __init__(
        self,
        config_dir: Path,
        offline: bool = False,
        filter_logs: bool = True,
    ):
        ...
    
    async def send(
        self, 
        message: str, 
        timeout: float = 120.0
    ) -> TestResult:
        """Send message and wait for response."""
        ...
    
    async def start(self) -> None:
        """Initialize SpokeCore."""
        ...
    
    async def stop(self) -> None:
        """Cleanup."""
        ...
```

#### `TestResult`

```python
@dataclass
class TestResult:
    success: bool
    response: Optional[str]
    tool_calls: List[ToolCallRecord]
    error: Optional[str]
    duration_ms: int
    mode: str  # "local" or "online"
```

#### `ToolCallRecord`

```python
@dataclass  
class ToolCallRecord:
    name: str
    arguments: Dict[str, Any]
    result: Optional[str]
    error: Optional[str]
    success: bool
```

### Logging Configuration

When `--show-logs` is **NOT** set (default):
```python
os.environ["RUST_LOG"] = "off"
# Redirect stderr to /dev/null or log file
```

When `--show-logs` is set:
```python
# Don't modify RUST_LOG
# Let stderr pass through to terminal
logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)
```

### Differences from Interactive CLI

| Aspect | Interactive CLI | Test CLI |
|--------|-----------------|----------|
| Tool output | Truncated (40 chars) | Full |
| Welcome banner | Yes | No |
| Prompt | `> ` colored | None (or `test> ` in interactive) |
| Voice support | Yes | No |
| Settings menu | Yes | No |
| Slash commands | Yes | Minimal (`/quit` only in interactive) |
| Output format | ANSI colors | Plain or JSON |
| Exit behavior | Loop until /quit | Exit after response |

## Example Test Usage

### pytest integration

```python
import subprocess
import json

def test_time_skill():
    result = subprocess.run(
        ["python", "-m", "strawberry.ui.test_cli", 
         "What time is it?", "--json", "--offline"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["success"]
    assert any(tc["name"] == "python_exec" for tc in data["tool_calls"])
```

### Shell scripting

```bash
#!/bin/bash
response=$(python -m strawberry.ui.test_cli "Calculate 15 * 7" --quiet --offline)
if [[ "$response" == *"105"* ]]; then
    echo "PASS: Calculator skill works"
else
    echo "FAIL: Expected 105 in response"
    exit 1
fi
```

## Future Enhancements

- **`--skill` filter** — Only allow specific skills (for isolated testing)
- **`--mock-skill`** — Inject mock skill responses
- **`--record`** — Save conversation to file for replay
- **`--replay`** — Replay a recorded conversation
- **`--compare`** — Compare output against expected baseline
