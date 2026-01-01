# Actionable Review Findings for Strawberry AI Spoke

This document contains actionable findings from the peer review, focused on specific improvements that can be implemented.

## 🎯 Core System Improvements

### 1. Add Version Information
**File:** `src/strawberry/main.py`
**Action:** Add `--version` flag to CLI
```python
parser.add_argument(
    "--version",
    action="version",
    version=f"Strawberry AI Spoke {__version__}",
    help="Show version information and exit"
)
```

### 2. Make LLM Parameters Configurable
**File:** `src/strawberry/terminal.py`
**Action:** Move hardcoded temperature parameter to settings
```python
# Replace hardcoded 0.7 with configurable value
response = await self._hub_client.chat(
    messages=self._conversation_history,
    temperature=self.settings.llm.temperature,  # From config
)
```

### 3. Add Conversation History Limits
**File:** `src/strawberry/terminal.py`
**Action:** Prevent unbounded memory growth
```python
# After appending to conversation history
if len(self._conversation_history) > self.settings.conversation.max_history:
    self._conversation_history = self._conversation_history[-self.settings.conversation.max_history:]
```

## ⚙️ Configuration System Improvements

### 4. Add LLM Configuration
**File:** `src/strawberry/config/settings.py`
```python
class LLMConfig(BaseModel):
    """Large Language Model configuration."""
    temperature: float = 0.7
    max_tokens: int = 500
    top_p: float = 1.0
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0

class Settings(BaseModel):
    # ... existing fields ...
    llm: LLMConfig = Field(default_factory=LLMConfig)
```

### 5. Add Conversation Settings
**File:** `src/strawberry/config/settings.py`
```python
class ConversationConfig(BaseModel):
    """Conversation history management."""
    max_history: int = 50
    max_tokens: int = 4000
    timeout_minutes: int = 30

class Settings(BaseModel):
    # ... existing fields ...
    conversation: ConversationConfig = Field(default_factory=ConversationConfig)
```

### 6. Improve Error Handling
**File:** `src/strawberry/config/loader.py`
```python
# Add proper error handling for YAML parsing
try:
    with open(config_path) as f:
        config_data = yaml.safe_load(f) or {}
except yaml.YAMLError as e:
    logger.error(f"Invalid YAML in config file: {e}")
    raise ConfigurationError(f"Invalid config: {e}") from e
except IOError as e:
    logger.error(f"Cannot read config file: {e}")
    raise ConfigurationError(f"Cannot read config: {e}") from e
```

## 🌐 Hub Integration Improvements

### 7. Add Retry Logic
**File:** `src/strawberry/hub/client.py`
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def _retry_request(self, method, url, **kwargs):
    """Retry failed requests with exponential backoff."""
    try:
        response = await method(url, **kwargs)
        self._check_response(response)
        return response
    except HubError as e:
        if e.status_code >= 500:  # Retry on server errors
            raise
        # Don't retry on client errors (4xx)
```

### 8. Add Circuit Breaker
**File:** `src/strawberry/hub/client.py`
```python
from pybreaker import CircuitBreaker

class HubClient:
    def __init__(self, config: HubConfig):
        self.config = config
        self._circuit_breaker = CircuitBreaker(fail_max=5, reset_timeout=60)
    
    async def chat(self, messages, **kwargs):
        return self._circuit_breaker.call(
            lambda: self._chat_impl(messages, **kwargs)
        )
```

### 9. Add Configurable Timeouts
**File:** `src/strawberry/hub/client.py`
```python
# Extend HubConfig
@dataclass
class HubConfig:
    url: str
    token: str
    timeout: float = 30.0
    connect_timeout: float = 10.0
    read_timeout: float = 30.0
    write_timeout: float = 30.0

# Use in client creation
self._client = httpx.AsyncClient(
    base_url=self.config.url,
    headers={"Authorization": f"Bearer {self.config.token}"},
    timeout=httpx.Timeout(
        connect=self.config.connect_timeout,
        read=self.config.read_timeout,
        write=self.config.write_timeout,
    )
)
```

## 🧩 Skill System Improvements

### 10. Add Skill Validation
**File:** `src/strawberry/skills/loader.py`
```python
def _validate_skill_method(self, method: SkillMethod) -> bool:
    """Validate skill method signature and documentation."""
    # Check for required docstring
    if not method.docstring or len(method.docstring.strip()) < 10:
        logger.warning(f"Method {method.name} has insufficient documentation")
        return False
    
    # Check for type hints
    if "->" not in method.signature:
        logger.warning(f"Method {method.name} missing return type annotation")
        return False
    
    return True
```

### 11. Enhance Search with Relevance Ranking
**File:** `src/strawberry/skills/registry.py`
```python
def _rank_skill_match(self, skill: SkillInfo, method: SkillMethod, query: str) -> float:
    """Calculate relevance score for skill/method match."""
    score = 0.0
    query_lower = query.lower()
    
    # Exact match in method name
    if query_lower == method.name.lower():
        score += 10.0
    
    # Exact match in skill name
    if query_lower == skill.name.lower():
        score += 5.0
    
    # Substring matches
    if query_lower in method.name.lower():
        score += 3.0
    if query_lower in skill.name.lower():
        score += 2.0
    if method.docstring and query_lower in method.docstring.lower():
        score += 1.0
    
    return score
```

### 12. Add Skill Caching
**File:** `src/strawberry/skills/registry.py`
```python
class SkillRegistry:
    def __init__(self, ...):
        self._remote_skills_cache: Dict[str, List[Dict[str, Any]]] = {}
        self._cache_ttl = 60.0  # 60 seconds
        self._last_cache_time = 0.0

async def _get_cached_remote_skills(self) -> List[Dict[str, Any]]:
    """Get remote skills with caching."""
    current_time = time.time()
    
    # Return cached results if still valid
    if (current_time - self._last_cache_time) < self._cache_ttl:
        return self._remote_skills_cache.get("", [])
    
    # Fetch fresh results
    try:
        results = await self.hub_client.list_skills()
        self._remote_skills_cache[""] = results
        self._last_cache_time = current_time
        return results
    except Exception as e:
        logger.error(f"Failed to fetch remote skills: {e}")
        return self._remote_skills_cache.get("", [])
```

## 🔄 Conversation Pipeline Improvements

### 13. Add Processing Timeouts
**File:** `src/strawberry/pipeline/conversation.py`
```python
def _process_speech(self, audio: np.ndarray) -> None:
    # Add timeout for processing
    def processing_task():
        try:
            # ... existing processing code ...
        except Exception as e:
            self._emit(EventType.ERROR, {"error": str(e), "stage": "processing"})
    
    # Run with timeout
    processing_thread = threading.Thread(target=processing_task, daemon=True)
    processing_thread.start()
    processing_thread.join(timeout=30.0)  # 30 second timeout
    
    if processing_thread.is_alive():
        self._emit(EventType.ERROR, {"error": "Processing timeout", "stage": "processing"})
        self._set_state(PipelineState.LISTENING)
```

### 14. Enhance Interrupt Detection
**File:** `src/strawberry/pipeline/conversation.py`
```python
def _check_interrupt(self, frame: np.ndarray) -> None:
    """Enhanced interrupt detection."""
    # Check volume level
    volume = np.max(np.abs(frame))
    if volume > self._interrupt_volume_threshold:
        self._interrupt_counter += 1
        if self._interrupt_counter >= 3:  # 3 consecutive loud frames
            self._handle_interrupt()
            return
    else:
        self._interrupt_counter = 0
    
    # Check wake word (existing logic)
    keyword_index = self._wake_detector.process(frame)
    if keyword_index >= 0:
        self._handle_interrupt()

def _handle_interrupt(self):
    """Handle confirmed interrupt."""
    self._audio_player.stop()
    self._emit(EventType.INTERRUPT_DETECTED)
    self._start_recording()
```

### 15. Add Conversation Context
**File:** `src/strawberry/pipeline/conversation.py`
```python
class ConversationPipeline:
    def __init__(self, ...):
        self._conversation_history = []
        self._conversation_context = {}
    
    def _process_speech(self, audio: np.ndarray) -> None:
        # ... transcription ...
        
        # Add to conversation history
        self._conversation_history.append({
            "role": "user",
            "content": result.text,
            "timestamp": time.time()
        })
        
        # Call response handler with context
        response_text = self._response_handler(result.text, self._conversation_context)
        
        # Add assistant response
        self._conversation_history.append({
            "role": "assistant",
            "content": response_text,
            "timestamp": time.time()
        })
```

## 📋 Implementation Priority

### High Priority (Critical for Production)
1. Add version information
2. Make LLM parameters configurable
3. Add conversation history limits
4. Add retry logic to Hub client
5. Add circuit breaker pattern
6. Add processing timeouts

### Medium Priority (Important Enhancements)
7. Add LLM configuration
8. Add conversation settings
9. Enhance search with relevance ranking
10. Add skill caching
11. Enhance interrupt detection
12. Add conversation context

### Low Priority (Nice to Have)
13. Add skill validation
14. Add configurable timeouts
15. Add logging configuration

## ✅ Next Steps

1. **Implement high-priority items first** (critical for stability)
2. **Add comprehensive tests** for new functionality
3. **Update documentation** with new features
4. **Monitor performance** after changes
5. **Iterate based on usage** patterns

Each of these improvements is actionable and can be implemented independently. The code examples provide specific guidance for implementation.