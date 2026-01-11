"""Sync manager for bidirectional sync between local storage and Hub."""

import asyncio
import logging
from typing import Optional

from ..hub import HubClient, HubError
from .session_db import LocalSessionDB

logger = logging.getLogger(__name__)


class SyncManager:
    """Manages sync between local storage and Hub.

    Handles:
    - Pushing local sessions/messages to Hub
    - Pulling remote sessions/messages from Hub
    - Processing the sync queue for offline operations
    """

    # Max retries for sync operations
    MAX_RETRY_ATTEMPTS = 3

    # Batch size for syncing
    BATCH_SIZE = 10

    # Default sync window (days)
    SYNC_DAYS = 30

    def __init__(self, db: LocalSessionDB, hub_client: Optional[HubClient] = None):
        """Initialize sync manager.

        Args:
            db: Local session database
            hub_client: Hub client (can be None if offline)
        """
        self.db = db
        self.hub_client = hub_client
        self._sync_in_progress = False
        self._sync_task: Optional[asyncio.Task] = None

    def set_hub_client(self, hub_client: Optional[HubClient]) -> None:
        """Set or update the Hub client.

        Args:
            hub_client: Hub client instance
        """
        self.hub_client = hub_client

    async def _hub_available(self) -> bool:
        """Check if Hub is available."""
        if not self.hub_client:
            return False
        try:
            return await self.hub_client.health()
        except Exception:
            return False

    async def sync_all(self) -> bool:
        """Full bidirectional sync.

        Returns:
            True if sync completed successfully
        """
        if self._sync_in_progress:
            logger.debug("Sync already in progress, skipping")
            return False

        if not await self._hub_available():
            logger.debug("Hub not available, skipping sync")
            return False

        self._sync_in_progress = True
        try:
            # 1. Push pending local changes to Hub
            await self._push_pending()

            # 2. Pull remote sessions we don't have locally
            await self._pull_remote()

            logger.info("Sync completed successfully")
            return True

        except Exception as e:
            logger.error(f"Sync failed: {e}")
            return False

        finally:
            self._sync_in_progress = False

    async def pull_remote_metadata(self) -> bool:
        """Pull remote session metadata and merge into local storage.

        This is a lightweight "read-side" sync used by the UI to keep session
        titles consistent with the Hub when connected.

        Returns:
            True if pull completed (or was not needed), False if Hub unavailable.
        """
        if not await self._hub_available():
            return False

        await self._pull_remote()
        return True

    async def _push_pending(self) -> None:
        """Push queued operations to Hub."""
        pending = self.db.get_pending_sync()

        if not pending:
            logger.debug("No pending sync operations")
            return

        logger.info(f"Pushing {len(pending)} pending sync operations")

        for op in pending:
            if op.attempts >= self.MAX_RETRY_ATTEMPTS:
                logger.warning(f"Sync operation {op.id} exceeded max retries, removing")
                self.db.remove_from_sync_queue(op.id)
                continue

            try:
                if op.operation == "create_session":
                    await self._sync_create_session(op)

                elif op.operation == "add_message":
                    await self._sync_add_message(op)

                elif op.operation == "delete_session":
                    await self._sync_delete_session(op)

                # Success - remove from queue
                self.db.remove_from_sync_queue(op.id)

            except HubError as e:
                logger.warning(f"Sync failed for {op.operation}: {e}")
                self.db.increment_sync_attempts(op.id)

            except Exception as e:
                logger.error(f"Unexpected error syncing {op.operation}: {e}")
                self.db.increment_sync_attempts(op.id)

    async def _sync_create_session(self, op) -> None:
        """Sync a create_session operation."""
        local_id = op.payload.get("local_id")
        if not local_id:
            logger.error("create_session operation missing local_id")
            return

        # Check if already synced
        session = self.db.get_session(local_id)
        if session and session.hub_id:
            logger.debug(f"Session {local_id} already synced")
            return

        # Create session on Hub
        hub_session = await self.hub_client.create_session()
        hub_id = hub_session.get("id")

        # Update local session with Hub ID
        self.db.mark_session_synced(local_id, hub_id)
        logger.info(f"Synced session {local_id} -> {hub_id}")

        # Sync any messages for this session
        await self._sync_session_messages(local_id, hub_id)

    async def _sync_add_message(self, op) -> None:
        """Sync an add_message operation."""
        local_session_id = op.payload.get("session_id")
        message_id = op.payload.get("message_id")
        role = op.payload.get("role")
        content = op.payload.get("content")

        if not all([local_session_id, message_id, role, content]):
            logger.error("add_message operation missing required fields")
            return

        # Get Hub session ID
        hub_session_id = self.db.get_hub_session_id(local_session_id)
        if not hub_session_id:
            # Session not yet synced - will be handled when session syncs
            logger.debug(f"Session {local_session_id} not yet synced, deferring message")
            return

        # Add message to Hub
        hub_message = await self.hub_client.add_session_message(
            hub_session_id, role, content
        )
        hub_message_id = hub_message.get("id")

        # Mark local message as synced
        self.db.mark_message_synced(message_id, hub_message_id)
        logger.debug(f"Synced message {message_id} -> {hub_message_id}")

    async def _sync_delete_session(self, op) -> None:
        """Sync a delete_session operation."""
        hub_session_id = op.payload.get("hub_session_id")
        if not hub_session_id:
            logger.debug("delete_session operation missing hub_session_id, already local-only")
            return

        try:
            await self.hub_client.delete_session(hub_session_id)
            logger.info(f"Deleted session {hub_session_id} from Hub")
        except HubError as e:
            if e.status_code == 404:
                # Already deleted
                logger.debug(f"Session {hub_session_id} already deleted from Hub")
            else:
                raise

    async def _sync_session_messages(self, local_session_id: str, hub_session_id: str) -> None:
        """Sync all unsynced messages for a session."""
        unsynced = self.db.get_unsynced_messages(local_session_id)

        for msg in unsynced:
            try:
                hub_message = await self.hub_client.add_session_message(
                    hub_session_id, msg.role, msg.content
                )
                self.db.mark_message_synced(msg.id, hub_message.get("id"))
            except Exception as e:
                logger.error(f"Failed to sync message {msg.id}: {e}")

    async def _pull_remote(self) -> None:
        """Pull remote sessions and merge into local storage.

        Behavior:
        - Import sessions/messages that don't exist locally.
        - Update local metadata (e.g. title) for sessions that already exist.
        """
        try:
            remote_sessions = await self.hub_client.list_sessions(days=self.SYNC_DAYS)
        except Exception as e:
            logger.error(f"Failed to fetch remote sessions: {e}")
            return

        imported_count = 0

        for remote in remote_sessions:
            hub_id = remote.get("id")
            if not hub_id:
                continue

            # If we already have this session, update local metadata.
            if self.db.has_hub_session(hub_id):
                local_session = self.db.get_session_by_hub_id(hub_id)
                if local_session:
                    remote_title = remote.get("title")
                    if remote_title is not None and remote_title != local_session.title:
                        self.db.update_session(local_session.id, title=remote_title)
                continue

            # Import remote session locally
            try:
                local_session = self.db.import_remote_session(remote)
                logger.debug(f"Imported remote session {hub_id} -> {local_session.id}")

                # Fetch and import messages
                messages = await self.hub_client.get_session_messages(hub_id)
                for msg in messages:
                    self.db.import_remote_message(local_session.id, msg)

                imported_count += 1

            except Exception as e:
                logger.error(f"Failed to import session {hub_id}: {e}")

        if imported_count > 0:
            logger.info(f"Imported {imported_count} remote sessions")

    # =========================================================================
    # Queue Operations
    # =========================================================================

    async def queue_create_session(self, local_session_id: str) -> None:
        """Queue a create_session operation for sync.

        Args:
            local_session_id: Local session ID
        """
        self.db.queue_sync_operation(
            "create_session",
            {"local_id": local_session_id},
        )

        # Try immediate sync if Hub available
        if await self._hub_available():
            await self._push_pending()

    async def queue_add_message(
        self,
        session_id: str,
        message_id: int,
        role: str,
        content: str,
    ) -> None:
        """Queue an add_message operation for sync.

        Args:
            session_id: Local session ID
            message_id: Local message ID
            role: Message role
            content: Message content
        """
        self.db.queue_sync_operation(
            "add_message",
            {
                "session_id": session_id,
                "message_id": message_id,
                "role": role,
                "content": content,
            },
        )

        # Try immediate sync if Hub available and session is synced
        hub_session_id = self.db.get_hub_session_id(session_id)
        if hub_session_id and await self._hub_available():
            await self._push_pending()

    async def queue_delete_session(self, local_session_id: str) -> None:
        """Queue a delete_session operation for sync.

        Args:
            local_session_id: Local session ID
        """
        # Get Hub ID before deleting locally
        hub_session_id = self.db.get_hub_session_id(local_session_id)

        # Delete locally (soft delete)
        self.db.delete_session(local_session_id, soft=True)

        # Queue for Hub deletion if synced
        if hub_session_id:
            self.db.queue_sync_operation(
                "delete_session",
                {"hub_session_id": hub_session_id},
            )

            # Try immediate sync
            if await self._hub_available():
                await self._push_pending()

    def get_pending_count(self) -> int:
        """Get count of pending sync operations.

        Returns:
            Number of pending operations
        """
        return self.db.get_pending_sync_count()

    # =========================================================================
    # Background Sync
    # =========================================================================

    def start_background_sync(self, interval_seconds: float = 30.0) -> None:
        """Start background sync task.

        Args:
            interval_seconds: Sync interval in seconds
        """
        if self._sync_task and not self._sync_task.done():
            logger.debug("Background sync already running")
            return

        self._sync_task = asyncio.create_task(
            self._background_sync_loop(interval_seconds)
        )
        logger.info(f"Started background sync (interval: {interval_seconds}s)")

    def stop_background_sync(self) -> None:
        """Stop background sync task."""
        if self._sync_task:
            self._sync_task.cancel()
            self._sync_task = None
            logger.info("Stopped background sync")

    async def _background_sync_loop(self, interval: float) -> None:
        """Background sync loop."""
        while True:
            try:
                await asyncio.sleep(interval)
                await self.sync_all()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Background sync error: {e}")
