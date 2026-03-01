"""Tests for online/local mode switching.

Covers:
- build_mode_switch_message() content
- build_tools_section() composability
- ChatSession.last_mode tracking
- SpokeCore._agent_loop mode switch injection
- Prompt composability (ROLE_SECTION, build_tools_section)
"""

from strawberry.skills.prompt import (
    ROLE_SECTION,
    build_mode_switch_message,
    build_tools_section,
)
from strawberry.skills.sandbox.proxy_gen import SkillMode
from strawberry.spoke_core.session import ChatSession

# =============================================================================
# build_mode_switch_message tests
# =============================================================================


class TestBuildModeSwitchMessage:
    """Tests for the mode switch message builder."""

    def test_online_message_mentions_devices_syntax(self):
        """Online switch should tell LLM to use devices.* syntax."""
        msg = build_mode_switch_message("online", skills=[])
        assert "devices." in msg
        assert "ONLINE" in msg

    def test_online_message_has_devices_syntax(self):
        """Online switch should include devices.* in the tool instructions."""
        msg = build_mode_switch_message("online", skills=[])
        assert "devices." in msg
        assert "ONLINE" in msg

    def test_local_message_mentions_device_syntax(self):
        """Local switch should tell LLM to use device.* syntax."""
        msg = build_mode_switch_message("local", skills=[])
        assert "device." in msg
        assert "LOCAL" in msg

    def test_local_message_has_device_syntax(self):
        """Local switch should include device.* in the tool instructions."""
        msg = build_mode_switch_message("local", skills=[])
        assert "device." in msg

    def test_online_message_mentions_tools(self):
        """Online switch should reference the 3 tools."""
        msg = build_mode_switch_message("online", skills=[])
        assert "search_skills" in msg
        assert "describe_function" in msg
        assert "python_exec" in msg

    def test_local_message_mentions_tools(self):
        """Local switch should reference the 3 tools."""
        msg = build_mode_switch_message("local", skills=[])
        assert "search_skills" in msg
        assert "describe_function" in msg
        assert "python_exec" in msg

    def test_online_message_is_system_notice(self):
        """Online switch should be formatted as a system notice."""
        msg = build_mode_switch_message("online", skills=[])
        assert msg.startswith("[System Notice:")

    def test_local_message_is_system_notice(self):
        """Local switch should be formatted as a system notice."""
        msg = build_mode_switch_message("local", skills=[])
        assert msg.startswith("[System Notice:")

    def test_online_message_requires_skill_rediscovery(self):
        """Online switch should instruct LLM to re-search for skills."""
        msg = build_mode_switch_message("online", skills=[])
        assert "search_skills" in msg
        assert "have changed" in msg or "rediscover" in msg

    def test_local_message_requires_skill_rediscovery(self):
        """Local switch should instruct LLM to re-search for skills."""
        msg = build_mode_switch_message("local", skills=[])
        assert "search_skills" in msg
        assert "have changed" in msg or "rediscover" in msg

    def test_online_message_mentions_python_exec(self):
        """Online switch should reference python_exec in the tool instructions."""
        msg = build_mode_switch_message("online", skills=[])
        assert "python_exec" in msg

    def test_local_message_mentions_python_exec(self):
        """Local switch should reference python_exec in the tool instructions."""
        msg = build_mode_switch_message("local", skills=[])
        assert "python_exec" in msg

    def test_local_message_has_example(self):
        """Local switch should include a python_exec example with device.* syntax."""
        msg = build_mode_switch_message("local", skills=[])
        assert "device.WeatherSkill" in msg

    def test_online_message_has_example(self):
        """Online switch should include a python_exec example with devices.* syntax."""
        msg = build_mode_switch_message("online", skills=[])
        assert "devices." in msg
        assert "WeatherSkill" in msg

    def test_local_message_explains_hub_offline(self):
        """Local switch should explain the Hub went offline."""
        msg = build_mode_switch_message("local", skills=[])
        assert "Hub" in msg and "offline" in msg

    def test_online_message_emphasizes_skills_available(self):
        """Online switch should emphasize skills from all devices are available."""
        msg = build_mode_switch_message("online", skills=[])
        assert "all connected devices" in msg

    def test_mentions_skills_changed(self):
        """Mode switch should mention that available skills have changed."""
        for mode in ("local", "online"):
            msg = build_mode_switch_message(mode, skills=[])
            assert "changed" in msg.lower() or "search_skills" in msg

    def test_skill_catalog_not_embedded(self):
        """Mode switch must NOT embed the skill catalog.

        Embedding skill names causes the LLM to attempt direct native
        tool calls (e.g. ``HassLightSet``) instead of using the
        python_exec workflow.  The LLM should use search_skills to
        rediscover available skills after a mode switch.
        """
        from unittest.mock import MagicMock

        fake_skill = MagicMock()
        fake_skill.name = "FakeSkill"
        fake_skill.class_obj.__doc__ = "A fake skill."
        fake_method = MagicMock()
        fake_method.name = "do_thing"
        fake_skill.methods = [fake_method]

        for mode in ("local", "online"):
            msg = build_mode_switch_message(mode, skills=[fake_skill])
            assert "FakeSkill" not in msg, (
                f"Skill catalog was embedded in {mode} mode switch message"
            )
            assert "Available Skills" not in msg


# =============================================================================
# ChatSession.last_mode tests
# =============================================================================


class TestSessionLastMode:
    """Tests for session-level mode tracking."""

    def test_new_session_has_no_last_mode(self):
        """Fresh session should have last_mode=None."""
        session = ChatSession()
        assert session.last_mode is None

    def test_last_mode_can_be_set(self):
        """Should be able to set last_mode."""
        session = ChatSession()
        session.last_mode = "local"
        assert session.last_mode == "local"

    def test_last_mode_survives_messages(self):
        """Adding messages should not affect last_mode."""
        session = ChatSession()
        session.last_mode = "online"
        session.add_message("user", "hello")
        session.add_message("assistant", "hi")
        assert session.last_mode == "online"

    def test_clear_resets_messages_not_mode(self):
        """clear() removes messages but should not affect last_mode."""
        session = ChatSession()
        session.last_mode = "local"
        session.add_message("user", "test")
        session.clear()
        assert len(session.messages) == 0
        # last_mode is preserved — it tracks the mode of the last turn,
        # not the message content
        assert session.last_mode == "local"


# =============================================================================
# Prompt composability tests
# =============================================================================


class TestPromptParts:
    """Tests that the prompt parts compose correctly."""

    def test_role_section_has_identity(self):
        """ROLE_SECTION should identify as Strawberry."""
        assert "Strawberry" in ROLE_SECTION

    def test_role_section_mentions_tools(self):
        """ROLE_SECTION should mention tool usage."""
        assert "tools" in ROLE_SECTION.lower()
        assert "search" in ROLE_SECTION.lower()

    def test_role_section_mentions_skills(self):
        """ROLE_SECTION should mention skills."""
        assert "skills" in ROLE_SECTION.lower()

    def test_role_section_is_mode_agnostic(self):
        """ROLE_SECTION should not reference specific mode names."""
        # device.<Skill> pattern is mode-agnostic (it's a template)
        assert "devices." not in ROLE_SECTION
        assert "local mode" not in ROLE_SECTION.lower()
        assert "online mode" not in ROLE_SECTION.lower()

    def test_local_tools_section_mentions_three_tools(self):
        """Local tools section should mention all 3 tools."""
        section = build_tools_section(SkillMode.LOCAL, [])
        assert "search_skills" in section
        assert "describe_function" in section
        assert "python_exec" in section

    def test_local_tools_section_uses_device_syntax(self):
        """Local tools section should use device.* syntax."""
        section = build_tools_section(SkillMode.LOCAL, [])
        assert "device." in section

    def test_online_tools_section_uses_devices_syntax(self):
        """Online tools section should use devices.* syntax."""
        section = build_tools_section(SkillMode.REMOTE, [])
        assert "devices." in section

    def test_local_tools_section_has_examples(self):
        """Local tools section should include usage examples."""
        section = build_tools_section(SkillMode.LOCAL, [])
        assert "Example" in section
        assert "WeatherSkill" in section

    def test_local_tools_section_has_important(self):
        """Local tools section should include important notes."""
        section = build_tools_section(SkillMode.LOCAL, [])
        assert "Important" in section
        assert "print()" in section

    def test_online_tools_section_has_important(self):
        """Online tools section should include important notes."""
        section = build_tools_section(SkillMode.REMOTE, [])
        assert "Important" in section


# =============================================================================
# Mode switch injection integration test (no real LLM needed)
# =============================================================================


class TestModeSwitchInjection:
    """Tests that mode switch messages get injected into sessions correctly.

    These tests simulate the ``send_message`` flow where the mode-switch
    notice is injected **before** the user message so the LLM sees the
    context change first, then the question.
    """

    @staticmethod
    def _simulate_send(session: ChatSession, mode: str, user_text: str):
        """Simulate the send_message mode-switch + user-message logic."""
        if session.last_mode is not None and mode != session.last_mode:
            session.add_message(
                "user", build_mode_switch_message(mode, skills=[])
            )
        session.last_mode = mode
        session.add_message("user", user_text)

    def test_first_message_no_injection(self):
        """First message in a session should not inject a mode switch."""
        session = ChatSession()
        assert session.last_mode is None
        self._simulate_send(session, "local", "hello")

        assert session.last_mode == "local"
        # Only the user message, no switch notice
        assert len(session.messages) == 1
        assert session.messages[0].content == "hello"

    def test_same_mode_no_injection(self):
        """Same mode as last time should not inject a mode switch."""
        session = ChatSession()
        self._simulate_send(session, "local", "hello")

        initial_count = len(session.messages)
        self._simulate_send(session, "local", "again")
        # Only the new user message added
        assert len(session.messages) == initial_count + 1

    def test_local_to_online_injects_message(self):
        """Switching from local to online should inject mode switch."""
        session = ChatSession()
        self._simulate_send(session, "local", "hello")
        session.add_message("assistant", "hi there")

        self._simulate_send(session, "online", "turn on lamp")

        # hello, assistant, mode_switch, turn on lamp
        assert len(session.messages) == 4
        assert "ONLINE" in session.messages[2].content
        assert session.messages[3].content == "turn on lamp"

    def test_online_to_local_injects_message(self):
        """Switching from online to local should inject mode switch."""
        session = ChatSession()
        self._simulate_send(session, "online", "hello")
        session.add_message("assistant", "hi there")

        self._simulate_send(session, "local", "what about now?")

        assert len(session.messages) == 4
        assert "LOCAL" in session.messages[2].content
        assert session.messages[3].content == "what about now?"

    def test_mode_switch_comes_before_user_message(self):
        """Mode switch notice must appear BEFORE the user's question."""
        session = ChatSession()
        self._simulate_send(session, "online", "hello")
        session.add_message("assistant", "hi")

        self._simulate_send(session, "local", "what about now?")

        # Find the mode switch and user message
        switch_idx = next(
            i for i, m in enumerate(session.messages)
            if "System Notice: Switched to" in m.content
        )
        user_idx = next(
            i for i, m in enumerate(session.messages)
            if m.content == "what about now?"
        )
        assert switch_idx < user_idx, (
            "Mode switch notice must come before the user's question"
        )

    def test_multiple_switches(self):
        """Multiple mode switches should inject a message each time."""
        session = ChatSession()

        # First turn: local (no injection)
        self._simulate_send(session, "local", "msg1")
        assert len(session.messages) == 1

        # Switch to online: switch_notice + msg2
        self._simulate_send(session, "online", "msg2")
        assert len(session.messages) == 3  # msg1 + switch + msg2

        # Switch back to local: switch_notice + msg3
        self._simulate_send(session, "local", "msg3")
        assert len(session.messages) == 5  # + switch + msg3

    def test_injected_message_role_is_user(self):
        """Mode switch messages should be injected as user role."""
        session = ChatSession()
        self._simulate_send(session, "online", "hello")
        self._simulate_send(session, "local", "bye")

        switch_msg = session.messages[1]  # switch is between hello and bye
        assert switch_msg.role == "user"
        assert "System Notice" in switch_msg.content
