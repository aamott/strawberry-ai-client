"""Porcupine wake word detector backend.

Requires: pip install pvporcupine
Also requires a Picovoice access key from https://picovoice.ai/
"""

from typing import List, Optional
import numpy as np

from ..base import WakeWordDetector


class PorcupineDetector(WakeWordDetector):
    """Wake word detection using Picovoice Porcupine.
    
    Porcupine is a highly accurate, lightweight wake word engine.
    It runs entirely on-device without needing external services.
    
    Built-in keywords: alexa, americano, blueberry, bumblebee, 
    computer, grapefruit, grasshopper, hey barista, hey google, 
    hey siri, jarvis, ok google, picovoice, porcupine, terminator
    
    Custom keywords require training at https://console.picovoice.ai/
    """
    
    def __init__(
        self,
        keywords: List[str],
        sensitivity: float = 0.5,
        access_key: Optional[str] = None,
    ):
        """Initialize Porcupine detector.
        
        Args:
            keywords: List of keywords to detect. Can be:
                      - Built-in keyword names (e.g., "jarvis", "computer")
                      - Paths to custom .ppn keyword files
            sensitivity: Detection sensitivity (0.0 to 1.0)
            access_key: Picovoice access key. If None, reads from
                       PICOVOICE_ACCESS_KEY environment variable.
                       
        Raises:
            ImportError: If pvporcupine is not installed
            ValueError: If access_key is not provided and not in environment
        """
        import os
        
        if access_key is None:
            access_key = os.environ.get("PICOVOICE_API_KEY")
        
        if not access_key:
            raise ValueError(
                "Picovoice access key required. Set PICOVOICE_API_KEY "
                "environment variable or pass access_key parameter."
            )
        
        import pvporcupine
        
        self._keywords_list = keywords
        self._sensitivity = sensitivity
        
        # Porcupine uses "keywords" for built-in and "keyword_paths" for custom
        # Try to detect which type each keyword is
        keyword_names = []
        keyword_paths = []
        
        for kw in keywords:
            if kw.endswith('.ppn') or '/' in kw or '\\' in kw:
                keyword_paths.append(kw)
            else:
                keyword_names.append(kw)
        
        # Create Porcupine instance
        if keyword_paths and keyword_names:
            raise ValueError(
                "Cannot mix built-in keywords and custom .ppn files. "
                "Use either all built-in or all custom keywords."
            )
        
        if keyword_paths:
            self._porcupine = pvporcupine.create(
                access_key=access_key,
                keyword_paths=keyword_paths,
                sensitivities=[sensitivity] * len(keyword_paths),
            )
        else:
            self._porcupine = pvporcupine.create(
                access_key=access_key,
                keywords=keyword_names,
                sensitivities=[sensitivity] * len(keyword_names),
            )
    
    @property
    def keywords(self) -> List[str]:
        return self._keywords_list
    
    @property
    def frame_length(self) -> int:
        return self._porcupine.frame_length
    
    @property
    def sample_rate(self) -> int:
        return self._porcupine.sample_rate
    
    def process(self, audio_frame: np.ndarray) -> int:
        """Process audio frame for wake word.
        
        Args:
            audio_frame: Audio samples (int16), must be exactly frame_length
            
        Returns:
            Index of detected keyword, or -1 if none
        """
        return self._porcupine.process(audio_frame)
    
    def cleanup(self) -> None:
        """Release Porcupine resources."""
        if self._porcupine is not None:
            self._porcupine.delete()
            self._porcupine = None

