"""Tests for VoiceInterface."""


from strawberry.ui.voice_interface import VoiceInterface


class TestVoiceInterface:
    """Tests for VoiceInterface class."""

    def test_can_create_without_dependencies(self):
        """VoiceInterface should be creatable without providing cores."""
        interface = VoiceInterface()
        assert interface is not None
        assert interface._spoke_core is None
        assert interface._voice_core is None

    def test_can_accept_external_cores(self):
        """VoiceInterface should accept external core instances."""
        # Create mock-like objects (just need to not be None)
        mock_spoke_core = object()
        mock_voice_core = object()

        interface = VoiceInterface(
            spoke_core=mock_spoke_core,
            voice_core=mock_voice_core,
        )

        assert interface._spoke_core is mock_spoke_core
        assert interface._voice_core is mock_voice_core
        # Should not own cores when provided externally
        assert interface._owns_spoke_core is False
        assert interface._owns_voice_core is False

    def test_owns_cores_when_none_provided(self):
        """VoiceInterface should own cores when none are provided."""
        interface = VoiceInterface()
        assert interface._owns_spoke_core is True
        assert interface._owns_voice_core is True

    def test_not_running_initially(self):
        """VoiceInterface should not be running when created."""
        interface = VoiceInterface()
        assert interface._running is False
        assert interface._session_id is None


class TestVoiceInterfaceModule:
    """Tests for VoiceInterface module exports."""

    def test_main_is_exported(self):
        """main function should be exported from module."""
        from strawberry.ui.voice_interface import main

        assert callable(main)

    def test_voice_interface_is_exported(self):
        """VoiceInterface class should be exported from module."""
        from strawberry.ui.voice_interface import VoiceInterface

        assert VoiceInterface is not None
