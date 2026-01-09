"""Session controller for the Strawberry AI UI.

This module owns local session persistence and optional Hub synchronization.
It provides a small API that MainWindow can delegate to.
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..models import ChatMessage
from ..storage import LocalSessionDB, SyncManager

logger = logging.getLogger(__name__)


@dataclass
class SessionListItem:
    """Serializable session data for the UI sidebar."""

    id: str
    hub_id: Optional[str]
    title: Optional[str]
    message_count: int
    last_activity: Any
    sync_status: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "hub_id": self.hub_id,
            "title": self.title,
            "message_count": self.message_count,
            "last_activity": self.last_activity,
            "sync_status": self.sync_status,
        }


class SessionController:
    """Owns local sessions and sync state.

    Responsibilities:
    - LocalSessionDB lifecycle
    - SyncManager lifecycle
    - Session CRUD (create/delete/list)
    - Message loading for a session (local first, Hub fallback)
    - Message creation + optional sync queueing
    """

    def __init__(
        self,
        db_path: Path,
    ) -> None:
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path

        self._db = LocalSessionDB(db_path)
        self._sync = SyncManager(self._db, None)

    @property
    def db(self) -> LocalSessionDB:
        return self._db

    @property
    def sync_manager(self) -> SyncManager:
        return self._sync

    def set_hub_client(self, hub_client) -> None:
        """Attach/detach Hub client used by SyncManager and Hub fallback reads."""
        self._sync.set_hub_client(hub_client)

    def get_pending_count(self) -> int:
        return self._sync.get_pending_count()

    async def sync_all(self) -> bool:
        return await self._sync.sync_all()

    async def create_local_session(self) -> str:
        session = self._db.create_session()
        await self._sync.queue_create_session(session.id)
        return session.id

    async def delete_local_session(self, session_id: str) -> None:
        await self._sync.queue_delete_session(session_id)

    async def delete_session(
        self,
        session_id: str,
        hub_client: Any,
        connected: bool,
    ) -> None:
        """Delete a session.

        For local-first storage we queue a delete op for Hub sync.
        If running in legacy Hub-only mode (no local session exists), we can delete
        directly from the Hub.
        """
        # Always queue the local delete (this is the source of truth).
        await self.delete_local_session(session_id)

        # Best-effort: if the session ID is a Hub session ID and we're online, delete it.
        if hub_client and connected:
            try:
                await self.delete_hub_session(hub_client, session_id)
            except Exception:
                logger.debug("Failed to delete Hub session (will rely on sync)")

    async def delete_hub_session(self, hub_client, session_id: str) -> None:
        await hub_client.delete_session(session_id)

    def list_local_sessions_for_sidebar(self) -> List[Dict[str, Any]]:
        sessions_data: List[Dict[str, Any]] = []
        local_sessions = self._db.list_sessions()
        for session in local_sessions:
            sessions_data.append(
                SessionListItem(
                    id=session.id,
                    hub_id=session.hub_id,
                    title=session.title,
                    message_count=self._db.get_session_message_count(session.id),
                    last_activity=session.last_activity,
                    sync_status=session.sync_status.value,
                ).to_dict()
            )
        return sessions_data

    async def list_sessions_for_sidebar(
        self,
        hub_client: Any,
        connected: bool,
    ) -> List[Dict[str, Any]]:
        """List sessions to display in the sidebar.

        Behavior:
        - Prefer local sessions when local storage exists.
        - If local storage is not available (legacy), fall back to Hub sessions.

        Args:
            hub_client: Hub client for remote session listing.
            connected: Whether the Hub is considered connected.

        Returns:
            List of session dicts for the sidebar.
        """

        # Local sessions are always preferred when available.
        local = self.list_local_sessions_for_sidebar()
        if local:
            return local

        if hub_client and connected:
            return await self.list_hub_sessions_for_sidebar(hub_client)

        return local

    async def list_hub_sessions_for_sidebar(self, hub_client) -> List[Dict[str, Any]]:
        return await hub_client.list_sessions()

    def load_local_session_messages(self, session_id: str) -> List[ChatMessage]:
        messages = self._db.get_messages(session_id)
        return [ChatMessage(role=m.role, content=m.content) for m in messages]

    async def load_session_messages(
        self,
        session_id: str,
        hub_client: Any,
        connected: bool,
    ) -> List[ChatMessage]:
        """Load messages for a session.

        Behavior:
        - Prefer local messages.
        - If the session doesn't exist locally (or local has no messages), and Hub is
          connected, fall back to Hub messages.
        """
        local_messages = self.load_local_session_messages(session_id)
        if local_messages:
            return local_messages

        if hub_client and connected:
            return await self.load_hub_session_messages(hub_client, session_id)

        return local_messages

    async def load_hub_session_messages(self, hub_client, session_id: str) -> List[ChatMessage]:
        messages = await hub_client.get_session_messages(session_id)
        return [ChatMessage(role=m["role"], content=m["content"]) for m in messages]

    def add_message_local(self, session_id: str, role: str, content: str) -> int:
        msg = self._db.add_message(session_id, role, content)
        return msg.id

    async def queue_add_message(
        self,
        session_id: str,
        local_message_id: int,
        role: str,
        content: str,
    ) -> None:
        await self._sync.queue_add_message(session_id, local_message_id, role, content)

    def close(self) -> None:
        self._db.close()

    async def close_async(self) -> None:
        # SyncManager currently doesn't own background tasks unless sync started.
        # Keep method for symmetry / future expansion.
        await asyncio.sleep(0)
        self.close()
