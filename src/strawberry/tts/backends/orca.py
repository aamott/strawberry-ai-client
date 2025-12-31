"""Orca TTS backend (Picovoice).

Requires: pip install pvorca
Also requires a Picovoice access key.
"""

from typing import Optional, Iterator
import os
import numpy as np

from ..base import TTSEngine, AudioChunk


class OrcaTTS(TTSEngine):
    """Text-to-Speech using Picovoice Orca.
    
    Orca is a streaming text-to-speech engine that:
    - Runs entirely on-device (no cloud API calls)
    - Supports streaming synthesis for low latency
    - Produces natural-sounding speech
    
    Pros:
    - Fast, offline operation
    - Streaming output for immediate playback
    - Natural voice quality
    
    Cons:
    - Requires Picovoice license
    - Limited voice options
    """
    
    def __init__(
        self,
        access_key: Optional[str] = None,
        model_path: Optional[str] = None,
    ):
        """Initialize Orca TTS.
        
        Args:
            access_key: Picovoice access key. If None, reads from
                       PICOVOICE_API_KEY environment variable.
            model_path: Path to custom model file. If None, uses default.
            
        Raises:
            ImportError: If pvorca is not installed
            ValueError: If access_key is not provided
        """
        if access_key is None:
            access_key = os.environ.get("PICOVOICE_API_KEY")
        
        if not access_key:
            raise ValueError(
                "Picovoice access key required. Set PICOVOICE_API_KEY "
                "environment variable or pass access_key parameter."
            )
        
        import pvorca
        
        if model_path:
            self._orca = pvorca.create(
                access_key=access_key,
                model_path=model_path,
            )
        else:
            self._orca = pvorca.create(access_key=access_key)
        
        self._sample_rate_val = self._orca.sample_rate
    
    @property
    def sample_rate(self) -> int:
        return self._sample_rate_val
    
    def synthesize(self, text: str) -> AudioChunk:
        """Synthesize complete text to audio.
        
        Args:
            text: Text to synthesize
            
        Returns:
            Complete audio chunk
        """
        # Use non-streaming API for complete synthesis
        pcm, _ = self._orca.synthesize(text)
        audio = np.array(pcm, dtype=np.int16)
        
        return AudioChunk(audio=audio, sample_rate=self._sample_rate_val)
    
    def synthesize_stream(self, text: str) -> Iterator[AudioChunk]:
        """Synthesize with streaming output.
        
        Yields audio chunks as they're generated for low-latency playback.
        
        Args:
            text: Text to synthesize
            
        Yields:
            Audio chunks
        """
        stream = self._orca.stream_open()
        
        try:
            # Feed text to streaming synthesizer
            for pcm in self._orca.synthesize_stream(stream, text):
                if pcm is not None and len(pcm) > 0:
                    audio = np.array(pcm, dtype=np.int16)
                    yield AudioChunk(audio=audio, sample_rate=self._sample_rate_val)
            
            # Flush any remaining audio
            pcm = self._orca.stream_flush(stream)
            if pcm is not None and len(pcm) > 0:
                audio = np.array(pcm, dtype=np.int16)
                yield AudioChunk(audio=audio, sample_rate=self._sample_rate_val)
                
        finally:
            self._orca.stream_close(stream)
    
    def cleanup(self) -> None:
        """Release Orca resources."""
        if self._orca is not None:
            self._orca.delete()
            self._orca = None

