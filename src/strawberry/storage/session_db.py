"""Local SQLite storage for sessions with sync tracking."""

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _to_utc(value)
    if value is None:
        return _utc_now()
    text = str(value).replace("Z", "+00:00")
    return _to_utc(datetime.fromisoformat(text))


class SyncStatus(str, Enum):
    """Session sync status."""

    LOCAL = "local"  # Created locally, not synced
    SYNCED = "synced"  # Synced with Hub
    PENDING_SYNC = "pending_sync"  # Has unsynced changes


@dataclass
class Session:
    """Local session model."""

    id: str  # Local UUID, never changes
    hub_id: Optional[str] = None  # Hub's ID after sync
    title: Optional[str] = None
    created_at: datetime = field(default_factory=_utc_now)
    last_activity: datetime = field(default_factory=_utc_now)
    is_synced: bool = False
    sync_status: SyncStatus = SyncStatus.LOCAL
    deleted_at: Optional[datetime] = None  # Soft delete timestamp
    # Mode tracking: "online" | "offline" | None
    # Tracks which mode prompt was last sent to avoid duplicates
    last_mode_prompt: Optional[str] = None


@dataclass
class Message:
    """Local message model."""

    id: int  # Local auto-increment ID
    session_id: str  # Local session ID
    role: str  # user, assistant, system
    content: str
    created_at: datetime = field(default_factory=_utc_now)
    hub_message_id: Optional[int] = None  # Hub's message ID after sync
    is_synced: bool = False
    sequence_number: int = 0  # Order within session


@dataclass
class SyncOperation:
    """Queued sync operation."""

    id: int
    operation: str  # create_session, add_message, delete_session
    payload: Dict[str, Any]
    created_at: datetime
    attempts: int = 0


class LocalSessionDB:
    """SQLite database for local session storage.

    Stores sessions and messages locally with tracking for Hub synchronization.
    """

    def __init__(self, db_path: Path):
        """Initialize local session database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_tables()

    def _get_conn(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _ensure_tables(self) -> None:
        """Create tables if they don't exist."""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.executescript(
            """
            -- Local sessions table
            CREATE TABLE IF NOT EXISTS local_sessions (
                id TEXT PRIMARY KEY,
                hub_id TEXT,
                title TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_synced BOOLEAN DEFAULT FALSE,
                sync_status TEXT DEFAULT 'local',
                deleted_at TIMESTAMP,
                last_mode_prompt TEXT
            );

            -- Local messages table
            CREATE TABLE IF NOT EXISTS local_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT REFERENCES local_sessions(id) ON DELETE CASCADE,
                hub_message_id INTEGER,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_synced BOOLEAN DEFAULT FALSE,
                sequence_number INTEGER DEFAULT 0
            );

            -- Sync queue for offline operations
            CREATE TABLE IF NOT EXISTS sync_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                attempts INTEGER DEFAULT 0
            );

            -- Index for faster lookups
            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON local_messages(session_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_hub_id
                ON local_sessions(hub_id);
            CREATE INDEX IF NOT EXISTS idx_sync_queue_created
                ON sync_queue(created_at);
        """
        )
        conn.commit()

        # Migration: Add last_mode_prompt column if missing (for existing databases)
        try:
            cursor.execute("PRAGMA table_info(local_sessions)")
            existing_cols = {row[1] for row in cursor.fetchall()}
            if "last_mode_prompt" not in existing_cols:
                cursor.execute(
                    "ALTER TABLE local_sessions ADD COLUMN last_mode_prompt TEXT"
                )
                conn.commit()
        except Exception:
            pass  # Best-effort migration

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # =========================================================================
    # Session Operations
    # =========================================================================

    def create_session(self, title: Optional[str] = None) -> Session:
        """Create a new local session.

        Args:
            title: Optional session title

        Returns:
            Created Session object
        """
        session_id = str(uuid.uuid4())
        now = _utc_now()

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO local_sessions (id, title, created_at, last_activity, sync_status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, title, now.isoformat(), now.isoformat(), SyncStatus.LOCAL.value),
        )
        conn.commit()

        return Session(
            id=session_id,
            title=title,
            created_at=now,
            last_activity=now,
            sync_status=SyncStatus.LOCAL,
        )

    def get_session(self, session_id: str) -> Optional[Session]:
        """Get a session by ID.

        Args:
            session_id: Local session ID

        Returns:
            Session object or None if not found
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM local_sessions WHERE id = ? AND deleted_at IS NULL",
            (session_id,),
        )
        row = cursor.fetchone()

        if row:
            return self._row_to_session(row)
        return None

    def list_sessions(self, include_deleted: bool = False) -> List[Session]:
        """List all local sessions.

        Args:
            include_deleted: Include soft-deleted sessions

        Returns:
            List of Session objects, newest first
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        if include_deleted:
            cursor.execute("SELECT * FROM local_sessions ORDER BY last_activity DESC")
        else:
            cursor.execute(
                """
                SELECT * FROM local_sessions
                WHERE deleted_at IS NULL
                ORDER BY last_activity DESC
                """
            )

        return [self._row_to_session(row) for row in cursor.fetchall()]

    def update_session(
        self,
        session_id: str,
        title: Optional[str] = None,
        hub_id: Optional[str] = None,
        sync_status: Optional[SyncStatus] = None,
    ) -> bool:
        """Update session fields.

        Args:
            session_id: Local session ID
            title: New title (if provided)
            hub_id: Hub session ID (if synced)
            sync_status: New sync status

        Returns:
            True if session was updated
        """
        updates = []
        params = []

        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if hub_id is not None:
            updates.append("hub_id = ?")
            params.append(hub_id)
        if sync_status is not None:
            updates.append("sync_status = ?")
            params.append(sync_status.value)
            # is_synced tracks whether this session is linked to a Hub session.
            # A session can be PENDING_SYNC and still be synced/linked.
            if sync_status == SyncStatus.SYNCED:
                updates.append("is_synced = ?")
                params.append(True)
            elif sync_status == SyncStatus.LOCAL:
                updates.append("is_synced = ?")
                params.append(False)

        if not updates:
            return False

        params.append(session_id)

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE local_sessions SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
        return cursor.rowcount > 0

    def delete_session(self, session_id: str, soft: bool = True) -> bool:
        """Delete a session.

        Args:
            session_id: Local session ID
            soft: If True, soft delete (set deleted_at). If False, hard delete.

        Returns:
            True if session was deleted
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        if soft:
            cursor.execute(
                "UPDATE local_sessions SET deleted_at = ? WHERE id = ?",
                (_utc_now().isoformat(), session_id),
            )
        else:
            cursor.execute("DELETE FROM local_sessions WHERE id = ?", (session_id,))
            cursor.execute(
                "DELETE FROM local_messages WHERE session_id = ?", (session_id,)
            )

        conn.commit()
        return cursor.rowcount > 0

    def mark_session_synced(self, local_id: str, hub_id: str) -> None:
        """Mark a session as synced with Hub.

        Args:
            local_id: Local session ID
            hub_id: Hub's session ID
        """
        self.update_session(
            local_id,
            hub_id=hub_id,
            sync_status=SyncStatus.SYNCED,
        )

    def get_hub_session_id(self, local_id: str) -> Optional[str]:
        """Get Hub session ID for a local session.

        Args:
            local_id: Local session ID

        Returns:
            Hub session ID or None if not synced
        """
        session = self.get_session(local_id)
        return session.hub_id if session else None

    def get_session_by_hub_id(self, hub_id: str) -> Optional[Session]:
        """Get a local session by Hub session ID.

        Args:
            hub_id: Hub session ID

        Returns:
            Local Session object or None if not found
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM local_sessions WHERE hub_id = ? AND deleted_at IS NULL",
            (hub_id,),
        )
        row = cursor.fetchone()

        if row:
            return self._row_to_session(row)
        return None

    def has_hub_session(self, hub_id: str) -> bool:
        """Check if we have a local copy of a Hub session.

        Args:
            hub_id: Hub session ID

        Returns:
            True if local session exists with this hub_id
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM local_sessions WHERE hub_id = ?", (hub_id,))
        return cursor.fetchone() is not None

    def import_remote_session(self, remote: Dict[str, Any]) -> Session:
        """Import a session from Hub.

        Args:
            remote: Session dict from Hub API

        Returns:
            Created local Session
        """
        session_id = str(uuid.uuid4())
        hub_id = remote.get("id")
        title = remote.get("title")
        created_at = remote.get("created_at", _utc_now().isoformat())
        last_activity = remote.get("last_activity", created_at)

        created_at_dt = _parse_datetime(created_at)
        last_activity_dt = _parse_datetime(last_activity)

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO local_sessions
                (id, hub_id, title, created_at, last_activity, is_synced, sync_status)
            VALUES (?, ?, ?, ?, ?, TRUE, 'synced')
            """,
            (
                session_id,
                hub_id,
                title,
                created_at_dt.isoformat(),
                last_activity_dt.isoformat(),
            ),
        )
        conn.commit()

        return Session(
            id=session_id,
            hub_id=hub_id,
            title=title,
            created_at=created_at_dt,
            last_activity=last_activity_dt,
            is_synced=True,
            sync_status=SyncStatus.SYNCED,
        )

    # =========================================================================
    # Message Operations
    # =========================================================================

    def add_message(self, session_id: str, role: str, content: str) -> Message:
        """Add a message to a session.

        Args:
            session_id: Local session ID
            role: Message role (user, assistant, system)
            content: Message content

        Returns:
            Created Message object
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        # Get next sequence number
        cursor.execute(
            "SELECT COALESCE(MAX(sequence_number), 0) + 1"
            " FROM local_messages WHERE session_id = ?",
            (session_id,),
        )
        seq_num = cursor.fetchone()[0]

        now = _utc_now()
        cursor.execute(
            """
            INSERT INTO local_messages
                (session_id, role, content,
                 created_at, sequence_number)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, role, content, now.isoformat(), seq_num),
        )
        message_id = cursor.lastrowid

        # Update session last_activity
        cursor.execute(
            "UPDATE local_sessions SET last_activity = ? WHERE id = ?",
            (now.isoformat(), session_id),
        )
        conn.commit()

        return Message(
            id=message_id,
            session_id=session_id,
            role=role,
            content=content,
            created_at=now,
            sequence_number=seq_num,
        )

    def get_messages(self, session_id: str) -> List[Message]:
        """Get all messages for a session.

        Args:
            session_id: Local session ID

        Returns:
            List of Message objects in order
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM local_messages
            WHERE session_id = ?
            ORDER BY sequence_number ASC
            """,
            (session_id,),
        )
        return [self._row_to_message(row) for row in cursor.fetchall()]

    def mark_message_synced(
        self, message_id: int, hub_message_id: Optional[int] = None
    ) -> None:
        """Mark a message as synced.

        Args:
            message_id: Local message ID
            hub_message_id: Hub's message ID
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE local_messages SET is_synced = TRUE, hub_message_id = ? WHERE id = ?",
            (hub_message_id, message_id),
        )
        conn.commit()

    def import_remote_message(self, session_id: str, remote: Dict[str, Any]) -> Message:
        """Import a message from Hub.

        Args:
            session_id: Local session ID
            remote: Message dict from Hub API

        Returns:
            Created local Message
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        # Get next sequence number
        cursor.execute(
            "SELECT COALESCE(MAX(sequence_number), 0) + 1"
            " FROM local_messages WHERE session_id = ?",
            (session_id,),
        )
        seq_num = cursor.fetchone()[0]

        created_at_dt = _parse_datetime(
            remote.get("created_at", _utc_now().isoformat())
        )

        cursor.execute(
            """
            INSERT INTO local_messages
                (session_id, hub_message_id, role,
                 content, created_at, is_synced,
                 sequence_number)
            VALUES (?, ?, ?, ?, ?, TRUE, ?)
            """,
            (
                session_id,
                remote.get("id"),
                remote.get("role"),
                remote.get("content"),
                created_at_dt.isoformat(),
                seq_num,
            ),
        )
        message_id = cursor.lastrowid
        conn.commit()

        return Message(
            id=message_id,
            session_id=session_id,
            role=remote.get("role"),
            content=remote.get("content"),
            created_at=created_at_dt,
            hub_message_id=remote.get("id"),
            is_synced=True,
            sequence_number=seq_num,
        )

    def get_unsynced_messages(self, session_id: str) -> List[Message]:
        """Get unsynced messages for a session.

        Args:
            session_id: Local session ID

        Returns:
            List of unsynced Message objects
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM local_messages
            WHERE session_id = ? AND is_synced = FALSE
            ORDER BY sequence_number ASC
            """,
            (session_id,),
        )
        return [self._row_to_message(row) for row in cursor.fetchall()]

    # =========================================================================
    # Sync Queue Operations
    # =========================================================================

    def queue_sync_operation(self, operation: str, payload: Dict[str, Any]) -> int:
        """Add operation to sync queue.

        Args:
            operation: Operation type (create_session, add_message, delete_session)
            payload: Operation payload

        Returns:
            Queue entry ID
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO sync_queue (operation, payload) VALUES (?, ?)",
            (operation, json.dumps(payload)),
        )
        conn.commit()
        return cursor.lastrowid

    def get_pending_sync(self) -> List[SyncOperation]:
        """Get all pending sync operations.

        Returns:
            List of SyncOperation objects
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sync_queue ORDER BY created_at ASC")
        return [self._row_to_sync_op(row) for row in cursor.fetchall()]

    def get_pending_sync_count(self) -> int:
        """Get count of pending sync operations.

        Returns:
            Number of pending operations
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM sync_queue")
        return cursor.fetchone()[0]

    def remove_from_sync_queue(self, op_id: int) -> None:
        """Remove operation from sync queue.

        Args:
            op_id: Queue entry ID
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sync_queue WHERE id = ?", (op_id,))
        conn.commit()

    def increment_sync_attempts(self, op_id: int) -> None:
        """Increment attempt counter for a sync operation.

        Args:
            op_id: Queue entry ID
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE sync_queue SET attempts = attempts + 1 WHERE id = ?",
            (op_id,),
        )
        conn.commit()

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _row_to_session(self, row: sqlite3.Row) -> Session:
        """Convert database row to Session object."""
        created_at = _parse_datetime(row["created_at"])
        last_activity = _parse_datetime(row["last_activity"])

        deleted_raw = row["deleted_at"]
        deleted_at = _parse_datetime(deleted_raw) if deleted_raw else None

        return Session(
            id=row["id"],
            hub_id=row["hub_id"],
            title=row["title"],
            created_at=created_at,
            last_activity=last_activity,
            is_synced=bool(row["is_synced"]),
            sync_status=SyncStatus(row["sync_status"]),
            deleted_at=deleted_at,
        )

    def _row_to_message(self, row: sqlite3.Row) -> Message:
        """Convert database row to Message object."""
        created_at = _parse_datetime(row["created_at"])

        return Message(
            id=row["id"],
            session_id=row["session_id"],
            role=row["role"],
            content=row["content"],
            created_at=created_at,
            hub_message_id=row["hub_message_id"],
            is_synced=bool(row["is_synced"]),
            sequence_number=row["sequence_number"],
        )

    def _row_to_sync_op(self, row: sqlite3.Row) -> SyncOperation:
        """Convert database row to SyncOperation object."""
        created_at = _parse_datetime(row["created_at"])

        return SyncOperation(
            id=row["id"],
            operation=row["operation"],
            payload=json.loads(row["payload"]),
            created_at=created_at,
            attempts=row["attempts"],
        )

    def get_session_message_count(self, session_id: str) -> int:
        """Get message count for a session.

        Args:
            session_id: Local session ID

        Returns:
            Number of messages
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM local_messages WHERE session_id = ?",
            (session_id,),
        )
        return cursor.fetchone()[0]
