"""Pipeline events for UI and external consumers."""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Any
from datetime import datetime


class EventType(Enum):
    """Types of pipeline events."""
    
    # State changes
    STATE_CHANGED = auto()
    
    # Wake word
    WAKE_WORD_DETECTED = auto()
    
    # Recording
    RECORDING_STARTED = auto()
    RECORDING_STOPPED = auto()
    VAD_SPEECH_START = auto()
    VAD_SPEECH_END = auto()
    
    # Transcription
    TRANSCRIPTION_STARTED = auto()
    TRANSCRIPTION_COMPLETE = auto()
    
    # Response
    RESPONSE_STARTED = auto()
    RESPONSE_TEXT = auto()
    RESPONSE_COMPLETE = auto()
    
    # TTS
    TTS_STARTED = auto()
    TTS_CHUNK = auto()
    TTS_COMPLETE = auto()
    
    # Errors
    ERROR = auto()


@dataclass
class PipelineEvent:
    """Event emitted by the conversation pipeline.
    
    Attributes:
        type: Type of event
        data: Event-specific data
        timestamp: When the event occurred
    """
    type: EventType
    data: Optional[Any] = None
    timestamp: datetime = field(default_factory=datetime.now)
    
    def __repr__(self) -> str:
        return f"PipelineEvent({self.type.name}, data={self.data!r})"

