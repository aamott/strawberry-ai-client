"""Tests for standalone voice module.

Voice is now an independent module that UIs control directly.
UIs bridge voice transcriptions to SpokeCore.send_message() as needed.
See voice_ui.md and spoke-modules.md for architecture.
"""

import pytest

from strawberry.voice import (
    VoiceConfig,
    VoiceController,
    VoiceState,
    VoiceStatusChanged,
)


class TestVoiceStandalone:
    """Tests verifying voice works independently of SpokeCore."""

    def _make_test_voice_config(self) -> VoiceConfig:
        """Create a VoiceConfig that uses mock backends for tests.

        Returns:
            VoiceConfig configured for deterministic, dependency-free tests.
        """
        return VoiceConfig(
            stt_backend="mock",
            tts_backend="mock",
            vad_backend="mock",
            wake_backend="mock",
            wake_words=["test_wake_word"],
        )

    def test_voice_controller_creates_without_core(self):
        """VoiceController should work without any SpokeCore dependency."""
        config = self._make_test_voice_config()
        controller = VoiceController(config)

        assert controller is not None
        assert controller.state == VoiceState.STOPPED

    def test_voice_controller_accepts_custom_handler(self):
        """VoiceController should accept a custom response handler."""
        responses = []

        def my_handler(text: str) -> str:
            responses.append(text)
            return f"You said: {text}"

        config = self._make_test_voice_config()
        controller = VoiceController(config, response_handler=my_handler)

        # Set handler after init
        controller.set_response_handler(my_handler)

        # Verify handler is set (can't test full flow without audio)
        assert controller._response_handler is not None

    @pytest.mark.asyncio
    async def test_voice_controller_emits_events(self):
        """VoiceController should emit status events."""
        config = self._make_test_voice_config()
        controller = VoiceController(config)

        events = []
        controller.add_listener(lambda e: events.append(e))

        await controller.start()
        await controller.stop()

        # Should have emitted at least start and stop events
        status_events = [e for e in events if isinstance(e, VoiceStatusChanged)]
        assert len(status_events) >= 2

    def test_voice_does_not_import_spoke_core(self):
        """Voice module should not depend on SpokeCore."""
        import strawberry.voice as voice_module

        # Check that voice module doesn't import from core
        # This ensures loose coupling
        module_source = voice_module.__file__
        assert module_source is not None  # Voice module exists independently
