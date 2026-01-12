"""Tests for offline mode components."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from strawberry.llm.offline_tracker import OfflineModeTracker
from strawberry.llm.tensorzero_client import ChatMessage, ChatResponse, TensorZeroClient
from strawberry.storage.session_db import LocalSessionDB, SyncStatus
from strawberry.storage.sync_manager import SyncManager
from strawberry.ui.session_controller import SessionController


class TestOfflineModeTracker:
    """Tests for OfflineModeTracker."""

    def test_initial_state(self):
        """Test initial state is online."""
        tracker = OfflineModeTracker()
        assert not tracker.is_offline
        assert tracker.last_hub_success is None
        assert tracker.last_variant is None

    def test_hub_response_stays_online(self):
        """Test that Hub responses keep us online."""
        tracker = OfflineModeTracker()

        response = ChatResponse(
            content="Hello",
            model="gpt-4",
            variant="hub",
            is_fallback=False,
        )
        tracker.on_response(response)

        assert not tracker.is_offline
        assert tracker.last_variant == "hub"
        assert tracker.last_hub_success is not None

    def test_single_fallback_stays_online(self):
        """Test that single fallback doesn't trigger offline mode."""
        tracker = OfflineModeTracker()

        response = ChatResponse(
            content="Hello",
            model="llama3.2:3b",
            variant="local_ollama",
            is_fallback=True,
        )
        tracker.on_response(response)

        assert not tracker.is_offline  # Need 2 consecutive fallbacks
        assert tracker.last_variant == "local_ollama"

    def test_consecutive_fallbacks_triggers_offline(self):
        """Test that consecutive fallbacks trigger offline mode."""
        tracker = OfflineModeTracker()

        response = ChatResponse(
            content="Hello",
            model="llama3.2:3b",
            variant="local_ollama",
            is_fallback=True,
        )

        # First fallback
        tracker.on_response(response)
        assert not tracker.is_offline

        # Second fallback - should trigger offline
        tracker.on_response(response)
        assert tracker.is_offline

    def test_hub_response_resets_offline(self):
        """Test that Hub response resets offline mode."""
        tracker = OfflineModeTracker()

        # Go offline
        fallback = ChatResponse(
            content="Hello",
            model="llama3.2:3b",
            variant="local_ollama",
            is_fallback=True,
        )
        tracker.on_response(fallback)
        tracker.on_response(fallback)
        assert tracker.is_offline

        # Hub response brings us back online
        hub_response = ChatResponse(
            content="Hello",
            model="gpt-4",
            variant="hub",
            is_fallback=False,
        )
        tracker.on_response(hub_response)
        assert not tracker.is_offline

    def test_listener_notification(self):
        """Test that listeners are notified of state changes."""
        tracker = OfflineModeTracker()
        notifications = []

        def listener(is_offline: bool):
            notifications.append(is_offline)

        tracker.add_listener(listener)

        # Go offline
        fallback = ChatResponse(
            content="Hello",
            model="llama3.2:3b",
            variant="local_ollama",
            is_fallback=True,
        )
        tracker.on_response(fallback)
        tracker.on_response(fallback)

        # Come back online
        hub_response = ChatResponse(
            content="Hello",
            model="gpt-4",
            variant="hub",
            is_fallback=False,
        )
        tracker.on_response(hub_response)

        assert notifications == [True, False]

    def test_get_status_text(self):
        """Test status text generation."""
        tracker = OfflineModeTracker()

        # Online status
        assert "Online" in tracker.get_status_text()

        # Go offline
        fallback = ChatResponse(
            content="Hello",
            model="llama3.2:3b",
            variant="local_ollama",
            is_fallback=True,
        )
        tracker.on_response(fallback)
        tracker.on_response(fallback)

        status = tracker.get_status_text("llama3.2:3b")
        assert "Offline" in status
        assert "llama3.2:3b" in status

    def test_pending_sync_count(self):
        """Test pending sync count tracking."""
        tracker = OfflineModeTracker()

        tracker.pending_sync_count = 5
        assert tracker.pending_sync_count == 5

        tracker.pending_sync_count = -1  # Should be clamped to 0
        assert tracker.pending_sync_count == 0


class TestLocalSessionDB:
    """Tests for LocalSessionDB."""

    @pytest.fixture
    def db(self, tmp_path: Path):
        """Create a temporary database."""
        db_path = tmp_path / "test_sessions.db"
        db = LocalSessionDB(db_path)
        yield db
        db.close()

    def test_create_session(self, db: LocalSessionDB):
        """Test session creation."""
        session = db.create_session(title="Test Session")

        assert session.id is not None
        assert session.title == "Test Session"
        assert session.sync_status == SyncStatus.LOCAL
        assert not session.is_synced

    def test_get_session(self, db: LocalSessionDB):
        """Test session retrieval."""
        created = db.create_session(title="Test")
        retrieved = db.get_session(created.id)

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.title == "Test"

    def test_list_sessions(self, db: LocalSessionDB):
        """Test listing sessions."""
        db.create_session(title="Session 1")
        db.create_session(title="Session 2")

        sessions = db.list_sessions()
        assert len(sessions) == 2

    def test_update_session(self, db: LocalSessionDB):
        """Test session update."""
        session = db.create_session()

        db.update_session(
            session.id,
            title="Updated Title",
            hub_id="hub-123",
            sync_status=SyncStatus.SYNCED,
        )

        updated = db.get_session(session.id)
        assert updated.title == "Updated Title"
        assert updated.hub_id == "hub-123"
        assert updated.sync_status == SyncStatus.SYNCED

    def test_delete_session_soft(self, db: LocalSessionDB):
        """Test soft delete."""
        session = db.create_session()
        db.delete_session(session.id, soft=True)

        # Should not appear in normal list
        sessions = db.list_sessions()
        assert len(sessions) == 0

        # Should appear in list with include_deleted
        sessions = db.list_sessions(include_deleted=True)
        assert len(sessions) == 1

    def test_add_message(self, db: LocalSessionDB):
        """Test adding messages."""
        session = db.create_session()

        msg1 = db.add_message(session.id, "user", "Hello")
        msg2 = db.add_message(session.id, "assistant", "Hi there!")

        assert msg1.role == "user"
        assert msg1.content == "Hello"
        assert msg1.sequence_number == 1

        assert msg2.role == "assistant"
        assert msg2.sequence_number == 2

    def test_get_messages(self, db: LocalSessionDB):
        """Test getting messages for a session."""
        session = db.create_session()
        db.add_message(session.id, "user", "Hello")
        db.add_message(session.id, "assistant", "Hi!")

        messages = db.get_messages(session.id)
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[1].role == "assistant"

    def test_sync_queue(self, db: LocalSessionDB):
        """Test sync queue operations."""
        # Queue operation
        op_id = db.queue_sync_operation(
            "create_session",
            {"local_id": "test-123"},
        )

        # Get pending
        pending = db.get_pending_sync()
        assert len(pending) == 1
        assert pending[0].operation == "create_session"

        # Remove from queue
        db.remove_from_sync_queue(op_id)
        pending = db.get_pending_sync()
        assert len(pending) == 0

    def test_mark_session_synced(self, db: LocalSessionDB):
        """Test marking session as synced."""
        session = db.create_session()
        db.mark_session_synced(session.id, "hub-456")

        updated = db.get_session(session.id)
        assert updated.hub_id == "hub-456"
        assert updated.sync_status == SyncStatus.SYNCED
        assert updated.is_synced

    def test_import_remote_session(self, db: LocalSessionDB):
        """Test importing a remote session."""
        remote = {
            "id": "hub-789",
            "title": "Remote Session",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_activity": datetime.now(timezone.utc).isoformat(),
        }

        session = db.import_remote_session(remote)
        assert session.hub_id == "hub-789"
        assert session.title == "Remote Session"
        assert session.is_synced


class TestSyncManager:
    """Tests for SyncManager."""

    @pytest.fixture
    def db(self, tmp_path: Path):
        """Create a temporary database."""
        db_path = tmp_path / "test_sync.db"
        db = LocalSessionDB(db_path)
        yield db
        db.close()

    @pytest.fixture
    def mock_hub_client(self):
        """Create a mock Hub client."""
        client = MagicMock()
        client.health = AsyncMock(return_value=True)
        client.create_session = AsyncMock(return_value={"id": "hub-session-1"})
        client.list_sessions = AsyncMock(return_value=[])
        client.add_session_message = AsyncMock(return_value={"id": 1})
        client.delete_session = AsyncMock()
        client.get_session_messages = AsyncMock(return_value=[])
        return client

    @pytest.mark.asyncio
    async def test_sync_all_when_hub_unavailable(self, db: LocalSessionDB):
        """Test sync does nothing when Hub is unavailable."""
        sync_manager = SyncManager(db, hub_client=None)
        result = await sync_manager.sync_all()
        assert not result

    @pytest.mark.asyncio
    async def test_queue_create_session(
        self, db: LocalSessionDB, mock_hub_client
    ):
        """Test queuing session creation for sync."""
        sync_manager = SyncManager(db, mock_hub_client)

        session = db.create_session()
        await sync_manager.queue_create_session(session.id)

        # Should have been synced immediately
        mock_hub_client.create_session.assert_called_once()

        # Session should now have hub_id
        updated = db.get_session(session.id)
        assert updated.hub_id == "hub-session-1"

    @pytest.mark.asyncio
    async def test_queue_add_message(
        self, db: LocalSessionDB, mock_hub_client
    ):
        """Test queuing message for sync."""
        sync_manager = SyncManager(db, mock_hub_client)

        session = db.create_session()
        db.mark_session_synced(session.id, "hub-session-1")
        msg = db.add_message(session.id, "user", "Hello")

        await sync_manager.queue_add_message(
            session.id, msg.id, "user", "Hello"
        )

        # Should have synced message
        mock_hub_client.add_session_message.assert_called_once_with(
            "hub-session-1", "user", "Hello"
        )

    @pytest.mark.asyncio
    async def test_add_message_deferred_not_removed(self, db: LocalSessionDB, mock_hub_client):
        """If a session has no hub_id yet, add_message ops should remain queued."""
        sync_manager = SyncManager(db, mock_hub_client)

        session = db.create_session()
        msg = db.add_message(session.id, "user", "Hello")
        await sync_manager.queue_add_message(session.id, msg.id, "user", "Hello")

        # Trigger sync: add_message should defer and remain queued.
        await sync_manager.sync_all()
        pending = db.get_pending_sync()
        assert any(op.operation == "add_message" for op in pending)

    @pytest.mark.asyncio
    async def test_update_session_deferred_then_synced(self, db: LocalSessionDB, mock_hub_client):
        """update_session ops should defer until hub_id exists, then sync."""
        mock_hub_client.update_session = AsyncMock(return_value={"id": "hub-session-1"})
        sync_manager = SyncManager(db, mock_hub_client)

        session = db.create_session(title="Old")
        await sync_manager.queue_update_session(session.id, "New")

        # No hub_id yet -> operation should remain
        pending = db.get_pending_sync()
        assert any(op.operation == "update_session" for op in pending)

        # Once session is synced, update_session should apply
        db.mark_session_synced(session.id, "hub-session-1")
        await sync_manager.sync_all()

        mock_hub_client.update_session.assert_called_once_with("hub-session-1", "New")
        pending2 = db.get_pending_sync()
        assert not any(op.operation == "update_session" for op in pending2)

    @pytest.mark.asyncio
    async def test_pull_remote_sessions(
        self, db: LocalSessionDB, mock_hub_client
    ):
        """Test pulling remote sessions."""
        mock_hub_client.list_sessions = AsyncMock(
            return_value=[
                {
                    "id": "remote-1",
                    "title": "Remote Session",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "last_activity": datetime.now(timezone.utc).isoformat(),
                }
            ]
        )
        mock_hub_client.get_session_messages = AsyncMock(return_value=[])

        sync_manager = SyncManager(db, mock_hub_client)
        await sync_manager.sync_all()

        # Should have imported the remote session
        assert db.has_hub_session("remote-1")

    def test_get_pending_count(self, db: LocalSessionDB):
        """Test getting pending sync count."""
        sync_manager = SyncManager(db, hub_client=None)

        db.queue_sync_operation("create_session", {"local_id": "1"})
        db.queue_sync_operation("create_session", {"local_id": "2"})

        assert sync_manager.get_pending_count() == 2

    @pytest.mark.asyncio
    async def test_pull_remote_metadata_updates_title(
        self, db: LocalSessionDB, mock_hub_client
    ):
        """Existing local sessions should get title updates from Hub."""
        local = db.create_session(title="Old Title")
        db.mark_session_synced(local.id, "hub-1")

        mock_hub_client.list_sessions = AsyncMock(
            return_value=[
                {
                    "id": "hub-1",
                    "title": "New Title",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "last_activity": datetime.now(timezone.utc).isoformat(),
                }
            ]
        )
        mock_hub_client.get_session_messages = AsyncMock(return_value=[])

        sync_manager = SyncManager(db, mock_hub_client)
        result = await sync_manager.pull_remote_metadata()
        assert result

        updated = db.get_session(local.id)
        assert updated.title == "New Title"


class TestSessionControllerHubIdMapping:
    """Tests for SessionController hub_id mapping and metadata merge."""

    @pytest.mark.asyncio
    async def test_list_sessions_for_sidebar_merges_remote_titles(self, tmp_path: Path):
        db_path = tmp_path / "test_controller.db"
        controller = SessionController(db_path)
        local_id = await controller.create_local_session()
        controller.db.mark_session_synced(local_id, "hub-xyz")

        hub_client = MagicMock()
        hub_client.health = AsyncMock(return_value=True)
        hub_client.list_sessions = AsyncMock(
            return_value=[
                {
                    "id": "hub-xyz",
                    "title": "Hub Renamed",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "last_activity": datetime.now(timezone.utc).isoformat(),
                }
            ]
        )
        hub_client.get_session_messages = AsyncMock(return_value=[])

        sessions = await controller.list_sessions_for_sidebar(hub_client, connected=True)
        assert sessions
        assert sessions[0]["title"] == "Hub Renamed"

        controller.close()

    @pytest.mark.asyncio
    async def test_load_session_messages_uses_hub_id(self, tmp_path: Path):
        db_path = tmp_path / "test_controller_messages.db"
        controller = SessionController(db_path)
        local_id = controller.db.create_session().id
        controller.db.mark_session_synced(local_id, "hub-abc")

        hub_client = MagicMock()
        hub_client.get_session_messages = AsyncMock(
            return_value=[{"role": "user", "content": "hi"}]
        )

        messages = await controller.load_session_messages(local_id, hub_client, connected=True)
        assert messages and messages[0].content == "hi"
        hub_client.get_session_messages.assert_called_once_with("hub-abc")

        controller.close()


class TestTensorZeroClient:
    """Tests for TensorZeroClient (embedded gateway)."""

    def test_initialization(self):
        """Test client initialization with config path."""
        client = TensorZeroClient(config_path="/path/to/config.toml")
        assert client.config_path == "/path/to/config.toml"
        assert client._gateway is None
        assert client._initialized is False

    def test_default_config_path(self):
        """Test default config path resolution."""
        client = TensorZeroClient()
        # Should resolve to config/tensorzero.toml relative to project root
        assert "tensorzero.toml" in client.config_path

    @pytest.mark.asyncio
    async def test_health_check_without_valid_config(self):
        """Test health check returns False with invalid config."""
        client = TensorZeroClient(config_path="/nonexistent/config.toml")
        result = await client.health()
        assert not result
        await client.close()

    def test_chat_message_dataclass(self):
        """Test ChatMessage dataclass."""
        msg = ChatMessage(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_chat_response_dataclass(self):
        """Test ChatResponse dataclass."""
        from strawberry.llm.tensorzero_client import ChatResponse
        response = ChatResponse(
            content="Hello!",
            model="gpt-4",
            variant="hub",
            is_fallback=False,
            inference_id="test-123",
            tool_calls=[],
            raw={},
        )
        assert response.content == "Hello!"
        assert response.variant == "hub"
        assert not response.is_fallback


class TestChatMessage:
    """Tests for ChatMessage dataclass."""

    def test_creation(self):
        """Test message creation."""
        msg = ChatMessage(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"


class TestChatResponse:
    """Tests for ChatResponse dataclass."""

    def test_hub_response(self):
        """Test Hub response detection."""
        response = ChatResponse(
            content="Hello",
            model="gpt-4",
            variant="hub",
            is_fallback=False,
        )
        assert not response.is_fallback

    def test_fallback_response(self):
        """Test fallback response detection."""
        response = ChatResponse(
            content="Hello",
            model="llama3.2:3b",
            variant="local_ollama",
            is_fallback=True,
        )
        assert response.is_fallback
