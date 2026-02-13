"""Tests for online/offline mode switching.

Covers:
- build_mode_switch_message() content
- ChatSession.last_mode tracking
- SpokeCore._agent_loop mode switch injection
- Prompt composability (BASE_ROLE_PROMPT, TOOL_LIST, etc.)
"""

from strawberry.skills.prompt import (
    BASE_ROLE_PROMPT,
    COMMON_RULES,
    COMMON_SEARCH_TIPS,
    DEFAULT_SYSTEM_PROMPT_TEMPLATE,
    OFFLINE_TOOL_INSTRUCTIONS,
    TOOL_LIST,
    build_mode_switch_message,
)
from strawberry.spoke_core.session import ChatSession

# =============================================================================
# build_mode_switch_message tests
# =============================================================================


class TestBuildModeSwitchMessage:
    """Tests for the mode switch message builder."""

    def test_online_message_mentions_devices_syntax(self):
        """Online switch should tell LLM to use devices.* syntax."""
        msg = build_mode_switch_message("online")
        assert "devices." in msg
        assert "ONLINE" in msg

    def test_online_message_warns_against_local_syntax(self):
        """Online switch should tell LLM not to use device.* syntax."""
        msg = build_mode_switch_message("online")
        assert "device.*" in msg
        assert "Do NOT" in msg

    def test_offline_message_mentions_device_syntax(self):
        """Offline switch should tell LLM to use device.* syntax."""
        msg = build_mode_switch_message("offline")
        assert "device." in msg
        assert "LOCAL" in msg

    def test_offline_message_warns_against_remote_syntax(self):
        """Offline switch should tell LLM not to use devices.* syntax."""
        msg = build_mode_switch_message("offline")
        assert "devices.*" in msg
        assert "Do NOT" in msg

    def test_online_message_mentions_tools(self):
        """Online switch should reference the 3 tools."""
        msg = build_mode_switch_message("online")
        assert "search_skills" in msg
        assert "describe_function" in msg
        assert "python_exec" in msg

    def test_offline_message_mentions_tools(self):
        """Offline switch should reference the 3 tools."""
        msg = build_mode_switch_message("offline")
        assert "search_skills" in msg
        assert "describe_function" in msg
        assert "python_exec" in msg

    def test_online_message_is_system_notice(self):
        """Online switch should be formatted as a system notice."""
        msg = build_mode_switch_message("online")
        assert msg.startswith("[System Notice:")

    def test_offline_message_is_system_notice(self):
        """Offline switch should be formatted as a system notice."""
        msg = build_mode_switch_message("offline")
        assert msg.startswith("[System Notice:")

    def test_online_message_requires_skill_rediscovery(self):
        """Online switch should instruct LLM to re-search for skills."""
        msg = build_mode_switch_message("online")
        assert "search_skills" in msg
        assert "may differ" in msg

    def test_offline_message_requires_skill_rediscovery(self):
        """Offline switch should instruct LLM to re-search for skills."""
        msg = build_mode_switch_message("offline")
        assert "search_skills" in msg
        assert "may differ" in msg

    def test_online_message_enforces_python_exec(self):
        """Online switch should reinforce that skills go through python_exec."""
        msg = build_mode_switch_message("online")
        assert "python_exec" in msg
        assert "Do NOT call skill methods directly" in msg

    def test_offline_message_enforces_python_exec(self):
        """Offline switch should reinforce that skills go through python_exec."""
        msg = build_mode_switch_message("offline")
        assert "python_exec" in msg
        assert "Do NOT call skill methods directly" in msg

    def test_offline_message_has_example(self):
        """Offline switch should include a python_exec example with device.* syntax."""
        msg = build_mode_switch_message("offline")
        assert "device.WeatherSkill" in msg

    def test_online_message_has_example(self):
        """Online switch should include a python_exec example with devices.* syntax."""
        msg = build_mode_switch_message("online")
        assert "devices." in msg
        assert "WeatherSkill" in msg

    def test_offline_message_emphasizes_skills_work(self):
        """Offline switch should emphasize local skills are functional."""
        msg = build_mode_switch_message("offline")
        assert "fully available and working" in msg

    def test_online_message_emphasizes_skills_available(self):
        """Online switch should emphasize skills from all devices are available."""
        msg = build_mode_switch_message("online")
        assert "all connected devices" in msg


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
        session.last_mode = "offline"
        assert session.last_mode == "offline"

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
        session.last_mode = "offline"
        session.add_message("user", "test")
        session.clear()
        assert len(session.messages) == 0
        # last_mode is preserved — it tracks the mode of the last turn,
        # not the message content
        assert session.last_mode == "offline"


# =============================================================================
# Prompt composability tests
# =============================================================================


class TestPromptParts:
    """Tests that the prompt parts compose correctly."""

    def test_base_role_prompt_is_short(self):
        """BASE_ROLE_PROMPT should be a brief identity statement."""
        assert "Strawberry" in BASE_ROLE_PROMPT
        assert len(BASE_ROLE_PROMPT) < 200

    def test_tool_list_mentions_three_tools(self):
        """TOOL_LIST should mention all 3 tools."""
        assert "search_skills" in TOOL_LIST
        assert "describe_function" in TOOL_LIST
        assert "python_exec" in TOOL_LIST

    def test_offline_instructions_use_device_syntax(self):
        """OFFLINE_TOOL_INSTRUCTIONS should use device.* syntax."""
        assert "device." in OFFLINE_TOOL_INSTRUCTIONS
        # device_manager is mentioned only in a prohibition ("Do NOT use")
        assert "Do NOT use" in OFFLINE_TOOL_INSTRUCTIONS
        assert "device_manager" in OFFLINE_TOOL_INSTRUCTIONS

    def test_offline_instructions_forbid_remote(self):
        """OFFLINE_TOOL_INSTRUCTIONS should forbid devices.* syntax."""
        assert "Do NOT use devices.*" in OFFLINE_TOOL_INSTRUCTIONS

    def test_common_search_tips_present(self):
        """COMMON_SEARCH_TIPS should have search guidance."""
        assert "search_skills" in COMMON_SEARCH_TIPS
        assert "action" in COMMON_SEARCH_TIPS.lower()

    def test_common_rules_present(self):
        """COMMON_RULES should have behavioral rules."""
        assert "python_exec" in COMMON_RULES
        assert "concise" in COMMON_RULES.lower()

    def test_default_template_includes_all_parts(self):
        """DEFAULT_SYSTEM_PROMPT_TEMPLATE should compose all parts."""
        template = DEFAULT_SYSTEM_PROMPT_TEMPLATE
        assert BASE_ROLE_PROMPT in template
        assert "search_skills" in template
        assert "device." in template
        assert "{skill_descriptions}" in template

    def test_default_template_has_offline_instructions(self):
        """Template should include offline-specific instructions."""
        assert "OFFLINE" in DEFAULT_SYSTEM_PROMPT_TEMPLATE
        assert "Do NOT use devices.*" in DEFAULT_SYSTEM_PROMPT_TEMPLATE


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
            session.add_message("user", build_mode_switch_message(mode))
        session.last_mode = mode
        session.add_message("user", user_text)

    def test_first_message_no_injection(self):
        """First message in a session should not inject a mode switch."""
        session = ChatSession()
        assert session.last_mode is None
        self._simulate_send(session, "offline", "hello")

        assert session.last_mode == "offline"
        # Only the user message, no switch notice
        assert len(session.messages) == 1
        assert session.messages[0].content == "hello"

    def test_same_mode_no_injection(self):
        """Same mode as last time should not inject a mode switch."""
        session = ChatSession()
        self._simulate_send(session, "offline", "hello")

        initial_count = len(session.messages)
        self._simulate_send(session, "offline", "again")
        # Only the new user message added
        assert len(session.messages) == initial_count + 1

    def test_offline_to_online_injects_message(self):
        """Switching from offline to online should inject mode switch."""
        session = ChatSession()
        self._simulate_send(session, "offline", "hello")
        session.add_message("assistant", "hi there")

        self._simulate_send(session, "online", "turn on lamp")

        # hello, assistant, mode_switch, turn on lamp
        assert len(session.messages) == 4
        assert "ONLINE" in session.messages[2].content
        assert session.messages[3].content == "turn on lamp"

    def test_online_to_offline_injects_message(self):
        """Switching from online to offline should inject mode switch."""
        session = ChatSession()
        self._simulate_send(session, "online", "hello")
        session.add_message("assistant", "hi there")

        self._simulate_send(session, "offline", "what about now?")

        assert len(session.messages) == 4
        assert "LOCAL" in session.messages[2].content
        assert session.messages[3].content == "what about now?"

    def test_mode_switch_comes_before_user_message(self):
        """Mode switch notice must appear BEFORE the user's question."""
        session = ChatSession()
        self._simulate_send(session, "online", "hello")
        session.add_message("assistant", "hi")

        self._simulate_send(session, "offline", "what about now?")

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

        # First turn: offline (no injection)
        self._simulate_send(session, "offline", "msg1")
        assert len(session.messages) == 1

        # Switch to online: switch_notice + msg2
        self._simulate_send(session, "online", "msg2")
        assert len(session.messages) == 3  # msg1 + switch + msg2

        # Switch back to offline: switch_notice + msg3
        self._simulate_send(session, "offline", "msg3")
        assert len(session.messages) == 5  # + switch + msg3

    def test_injected_message_role_is_user(self):
        """Mode switch messages should be injected as user role."""
        session = ChatSession()
        self._simulate_send(session, "online", "hello")
        self._simulate_send(session, "offline", "bye")

        switch_msg = session.messages[1]  # switch is between hello and bye
        assert switch_msg.role == "user"
        assert "System Notice" in switch_msg.content
