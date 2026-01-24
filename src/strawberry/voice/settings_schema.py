"""Settings schema definitions for VoiceCore.

This module defines the VOICE_CORE_SCHEMA for VoiceCore settings.
These settings control the voice processing pipeline including
STT, TTS, VAD, and wake word detection.
"""

from typing import List

from strawberry.shared.settings import FieldType, SettingField

# Voice Core settings schema
VOICE_CORE_SCHEMA: List[SettingField] = [
    # ─────────────────────────────────────────────────────────────────
    # STT Settings
    # ─────────────────────────────────────────────────────────────────
    SettingField(
        key="stt.order",
        label="STT Fallback Order",
        type=FieldType.TEXT,
        default="leopard,whisper,google",
        description=(
            "Comma-separated list of STT backends to try in order. "
            "If the first fails, the next is tried."
        ),
        group="stt",
    ),
    SettingField(
        key="stt.enabled",
        label="Enable Speech-to-Text",
        type=FieldType.CHECKBOX,
        default=True,
        description="Enable speech recognition",
        group="stt",
    ),

    # ─────────────────────────────────────────────────────────────────
    # TTS Settings
    # ─────────────────────────────────────────────────────────────────
    SettingField(
        key="tts.order",
        label="TTS Fallback Order",
        type=FieldType.TEXT,
        default="pocket,orca,piper,google",
        description=(
            "Comma-separated list of TTS backends to try in order. "
            "If the first fails, the next is tried."
        ),
        group="tts",
    ),
    SettingField(
        key="tts.enabled",
        label="Enable Text-to-Speech",
        type=FieldType.CHECKBOX,
        default=True,
        description="Enable voice output",
        group="tts",
    ),

    # ─────────────────────────────────────────────────────────────────
    # VAD Settings
    # ─────────────────────────────────────────────────────────────────
    SettingField(
        key="vad.order",
        label="VAD Backend Order",
        type=FieldType.TEXT,
        default="silero",
        description="Comma-separated list of VAD backends to try in order",
        group="vad",
    ),
    SettingField(
        key="vad.enabled",
        label="Enable Voice Activity Detection",
        type=FieldType.CHECKBOX,
        default=True,
        description="Enable VAD to detect when user stops speaking",
        group="vad",
    ),

    # ─────────────────────────────────────────────────────────────────
    # Wake Word Settings
    # ─────────────────────────────────────────────────────────────────
    SettingField(
        key="wakeword.phrase",
        label="Wake Word",
        type=FieldType.SELECT,
        options=[
            "computer", "jarvis", "alexa", "hey google", "ok google",
            "hey siri", "porcupine", "picovoice", "bumblebee", "terminator",
            "blueberry", "grapefruit", "grasshopper", "americano",
        ],
        default="computer",
        description="The phrase that activates the assistant (Porcupine built-in keywords)",
        group="wakeword",
    ),
    SettingField(
        key="wakeword.enabled",
        label="Enable Wake Word",
        type=FieldType.CHECKBOX,
        default=True,
        description="Listen for wake word to start interaction",
        group="wakeword",
    ),
    SettingField(
        key="wakeword.sensitivity",
        label="Wake Word Sensitivity",
        type=FieldType.NUMBER,
        default=0.5,
        min_value=0.0,
        max_value=1.0,
        description="How sensitive the wake word detection is (0.0-1.0)",
        group="wakeword",
    ),
    SettingField(
        key="wakeword.order",
        label="Wake Word Backend Order",
        type=FieldType.TEXT,
        default="porcupine",
        description="Comma-separated list of wake word backends to try",
        group="wakeword",
    ),

    # ─────────────────────────────────────────────────────────────────
    # Audio Settings
    # ─────────────────────────────────────────────────────────────────
    SettingField(
        key="audio.sample_rate",
        label="Sample Rate",
        type=FieldType.SELECT,
        options=["8000", "16000", "22050", "44100", "48000"],
        default="16000",
        description="Audio sample rate in Hz",
        group="audio",
    ),
    SettingField(
        key="audio.feedback_enabled",
        label="Audio Feedback",
        type=FieldType.CHECKBOX,
        default=True,
        description="Play sounds when wake word detected and processing starts",
        group="audio",
    ),
]
