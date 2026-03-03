"""TTS backend implementations."""

from .mock import MockTTS

__all__ = ["MockTTS"]


def get_orca_tts():
    """Get OrcaTTS class (requires pvorca)."""
    from .orca import OrcaTTS

    return OrcaTTS


def get_pocket_tts():
    """Get PocketTTS class (requires pocket-tts)."""
    from .pocket import PocketTTS

    return PocketTTS


def get_soprano_tts():
    """Get SopranoTTS class (requires soprano-tts and CUDA GPU)."""
    from .soprano import SopranoTTS

    return SopranoTTS


def get_sopro_tts():
    """Get SoproTTS class (requires sopro, supports CPU and voice cloning)."""
    from .sopro import SoproTTS

    return SoproTTS


def get_neutts_tts():
    """Get NeuTTSEngine class (requires neutts)."""
    from .neutts import NeuTTSEngine

    return NeuTTSEngine


def get_optispeech_tts():
    """Get OptiSpeechTTS class (requires optispeech)."""
    from .optispeech import OptiSpeechTTS

    return OptiSpeechTTS


def get_qwen3_tts():
    """Get Qwen3TTSEngine class (requires qwen-tts)."""
    from .qwen3_tts import Qwen3TTSEngine

    return Qwen3TTSEngine


def get_inworld_tts():
    """Get InworldTTS class (requires Inworld API key)."""
    from .inworld import InworldTTS

    return InworldTTS
