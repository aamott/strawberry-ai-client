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
    # General
    # ─────────────────────────────────────────────────────────────────
    SettingField(
        key="general.autostart",
        label="Auto-start Voice Engine",
        type=FieldType.CHECKBOX,
        default=False,
        description="Start the voice engine automatically when the app launches",
        group="general",
    ),
    SettingField(
        key="general.read_responses_aloud",
        label="Read Responses Aloud",
        type=FieldType.CHECKBOX,
        default=False,
        description=(
            "Always read assistant responses aloud via TTS, "
            "regardless of whether the message was typed or spoken"
        ),
        group="general",
    ),
    # ─────────────────────────────────────────────────────────────────
    # STT Settings
    # ─────────────────────────────────────────────────────────────────
    SettingField(
        key="stt.order",
        label="STT Fallback Order",
        type=FieldType.PROVIDER_SELECT,  # Selects active provider
        provider_type="stt",
        provider_namespace_template="voice.stt.{value}",
        options_provider="available_stt_backends",
        default=["leopard", "whisper", "google"],
        description=("Ordered list of STT backends. First one is active provider."),
        group="stt",
        metadata={
            "help_text": (
                "The order defines which STT engine to try first.\n"
                "If the first one fails (e.g. network error), the next one is used.\n"
                "Example: 'leopard,whisper'"
            )
        },
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
        type=FieldType.PROVIDER_SELECT,
        provider_type="tts",
        provider_namespace_template="voice.tts.{value}",
        options_provider="available_tts_backends",
        default=["pocket", "orca", "piper", "google"],
        description=("Ordered list of TTS backends. First one is active provider."),
        group="tts",
        metadata={
            "help_text": (
                "The order defines which TTS engine to try first.\n"
                "If the first one fails, the next one is used.\n"
                "Example: 'pocket,orca'"
            )
        },
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
        type=FieldType.PROVIDER_SELECT,
        provider_type="vad",
        provider_namespace_template="voice.vad.{value}",
        options_provider="available_vad_backends",
        default=["silero"],
        description="Ordered list of VAD backends.",
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
            "hey barista",
            "computer",
            "jarvis",
            "alexa",
            "hey google",
            "ok google",
            "hey siri",
            "porcupine",
            "picovoice",
            "bumblebee",
            "terminator",
            "blueberry",
            "grapefruit",
            "grasshopper",
            "americano",
            "pico clock",
            "smart mirror",
            "snowboy",
            "view glass",
        ],
        default="hey barista",
        description=(
            "The phrase that activates the assistant"
            " (Porcupine built-in keywords)"
        ),
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
        metadata={
            "help_text": (
                "Higher values trigger more easily (more false positives).\n"
                "Lower values require clearer speech (more false negatives).\n"
                "0.5 is a balanced default."
            )
        },
    ),
    SettingField(
        key="wakeword.order",
        label="Wake Word Backend Order",
        type=FieldType.PROVIDER_SELECT,
        provider_type="wakeword",
        provider_namespace_template="voice.wakeword.{value}",
        options_provider="available_wakeword_backends",
        default=["porcupine"],
        description="Ordered list of wake word backends.",
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
        metadata={
            "help_text": (
                "16000Hz is standard for speech recognition.\n"
                "44100Hz/48000Hz provides higher quality for music playback/TTS."
            )
        },
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
