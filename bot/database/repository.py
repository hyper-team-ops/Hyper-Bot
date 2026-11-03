"""SQLite implementation of the persistent file registry."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from bot.database.models import (
    DiscoveredMessage,
    FileRecord,
    MatchCandidate,
    StorageTopic,
)


class DuplicateFileError(ValueError):
    """A website ID or public token is already registered."""


class FileNotFoundError(LookupError):
    """The requested registry entry does not exist."""


class SQLiteFileRepository:
    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS file_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    website_id TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    public_token TEXT NOT NULL UNIQUE,
                    source_channel_id INTEGER NOT NULL,
                    file_type TEXT,
                    description TEXT,
                    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
                    strip_captions INTEGER NOT NULL DEFAULT 1 CHECK(strip_captions IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS file_messages (
                    file_record_id INTEGER NOT NULL REFERENCES file_records(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL CHECK(position >= 0),
                    message_id INTEGER NOT NULL CHECK(message_id > 0),
                    PRIMARY KEY(file_record_id, position),
                    UNIQUE(file_record_id, message_id)
                );
                CREATE INDEX IF NOT EXISTS idx_file_records_active_token
                    ON file_records(public_token, active);
                CREATE INDEX IF NOT EXISTS idx_file_records_title
                    ON file_records(title);
                CREATE INDEX IF NOT EXISTS idx_file_messages_message_id
                    ON file_messages(message_id);
                CREATE TABLE IF NOT EXISTS storage_topics (
                    source_chat_id INTEGER NOT NULL,
                    topic_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    discovered_at TEXT NOT NULL,
                    PRIMARY KEY(source_chat_id, topic_id)
                );
                CREATE TABLE IF NOT EXISTS discovered_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL CHECK(message_id > 0),
                    topic_id INTEGER,
                    topic_title TEXT,
                    filename TEXT,
                    caption TEXT,
                    file_size INTEGER,
                    mime_type TEXT,
                    media_group_id TEXT,
                    message_date TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'new',
                    created_at TEXT NOT NULL,
                    UNIQUE(source_chat_id, message_id)
                );
                CREATE INDEX IF NOT EXISTS idx_discovered_state
                    ON discovered_messages(state, topic_id);
                CREATE INDEX IF NOT EXISTS idx_discovered_media_group
                    ON discovered_messages(source_chat_id, media_group_id);
                CREATE TABLE IF NOT EXISTS match_candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    discovered_message_id INTEGER NOT NULL
                        REFERENCES discovered_messages(id) ON DELETE CASCADE,
                    website_file_id TEXT,
                    website_title TEXT,
                    confidence REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    decided_at TEXT,
                    UNIQUE(discovered_message_id, website_file_id)
                );
                CREATE INDEX IF NOT EXISTS idx_match_candidates_status
                    ON match_candidates(status, created_at);
                CREATE TABLE IF NOT EXISTS review_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id INTEGER NOT NULL REFERENCES match_candidates(id),
                    admin_user_id INTEGER NOT NULL,
                    decision TEXT NOT NULL,
                    notes TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS import_checkpoints (
                    source_chat_id INTEGER NOT NULL,
                    topic_id INTEGER NOT NULL DEFAULT 0,
                    last_message_id INTEGER NOT NULL DEFAULT 0,
                    complete INTEGER NOT NULL DEFAULT 0 CHECK(complete IN (0, 1)),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(source_chat_id, topic_id)
                );
                CREATE TABLE IF NOT EXISTS sync_state (
                    website_file_id TEXT PRIMARY KEY,
                    sheet_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    last_error TEXT,
                    updated_at TEXT NOT NULL
                );
                PRAGMA user_version = 2;
                """
            )

    @staticmethod
    def _discovered(row: sqlite3.Row) -> DiscoveredMessage:
        return DiscoveredMessage(
            id=row["id"], source_chat_id=row["source_chat_id"],
            message_id=row["message_id"], topic_id=row["topic_id"],
            topic_title=row["topic_title"], filename=row["filename"],
            caption=row["caption"], file_size=row["file_size"],
            mime_type=row["mime_type"], media_group_id=row["media_group_id"],
            message_date=datetime.fromisoformat(row["message_date"]),
            state=row["state"], created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _candidate(row: sqlite3.Row) -> MatchCandidate:
        return MatchCandidate(
            id=row["id"], discovered_message_id=row["discovered_message_id"],
            website_file_id=row["website_file_id"], website_title=row["website_title"],
            confidence=row["confidence"], status=row["status"], reason=row["reason"],
            created_at=datetime.fromisoformat(row["created_at"]),
            decided_at=(datetime.fromisoformat(row["decided_at"])
                        if row["decided_at"] else None),
        )

    def _assert_messages_available(
        self,
        connection: sqlite3.Connection,
        source_channel_id: int,
        message_ids: Sequence[int],
        *,
        excluding_record_id: int | None = None,
    ) -> None:
        if not message_ids:
            raise ValueError("A file mapping requires at least one message ID")
        placeholders = ",".join("?" for _ in message_ids)
        sql = f"""SELECT fm.message_id
            FROM file_messages AS fm
            JOIN file_records AS fr ON fr.id = fm.file_record_id
            WHERE fr.source_channel_id = ? AND fm.message_id IN ({placeholders})"""
        params: list[object] = [source_channel_id, *message_ids]
        if excluding_record_id is not None:
            sql += " AND fr.id != ?"
            params.append(excluding_record_id)
        collision = connection.execute(sql, params).fetchone()
        if collision is not None:
            raise DuplicateFileError(
                "A source message is already assigned to another website resource"
            )

    @staticmethod
    def _record(row: sqlite3.Row, message_ids: Sequence[int]) -> FileRecord:
        return FileRecord(
            id=row["id"],
            website_id=row["website_id"],
            title=row["title"],
            public_token=row["public_token"],
            source_channel_id=row["source_channel_id"],
            message_ids=tuple(message_ids),
            file_type=row["file_type"],
            description=row["description"],
            active=bool(row["active"]),
            strip_captions=bool(row["strip_captions"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _messages(
        self, connection: sqlite3.Connection, record_id: int
    ) -> tuple[int, ...]:
        rows = connection.execute(
            """SELECT message_id FROM file_messages
            WHERE file_record_id = ? ORDER BY position""",
            (record_id,),
        ).fetchall()
        return tuple(row["message_id"] for row in rows)

    def create(
        self,
        *,
        website_id: str,
        title: str,
        public_token: str,
        source_channel_id: int,
        message_ids: Sequence[int],
        file_type: str | None = None,
        description: str | None = None,
        strip_captions: bool = True,
    ) -> FileRecord:
        now = datetime.now(UTC).isoformat()
        try:
            with self._connection() as connection:
                self._assert_messages_available(
                    connection, source_channel_id, message_ids
                )
                cursor = connection.execute(
                    """INSERT INTO file_records
                    (website_id, title, public_token, source_channel_id, file_type,
                     description, strip_captions, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        website_id,
                        title,
                        public_token,
                        source_channel_id,
                        file_type,
                        description,
                        int(strip_captions),
                        now,
                        now,
                    ),
                )
                record_id = int(cursor.lastrowid)
                connection.executemany(
                    """INSERT INTO file_messages
                    (file_record_id, position, message_id) VALUES (?, ?, ?)""",
                    (
                        (record_id, position, message_id)
                        for position, message_id in enumerate(message_ids)
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateFileError(
                "Website ID, token, or message order conflicts with an existing entry"
            ) from exc
        record = self.get_by_website_id(website_id)
        assert record is not None
        return record

    def get_by_token(
        self, public_token: str, *, active_only: bool = True
    ) -> FileRecord | None:
        sql = "SELECT * FROM file_records WHERE public_token = ?"
        params: tuple[object, ...] = (public_token,)
        if active_only:
            sql += " AND active = 1"
        with self._connection() as connection:
            row = connection.execute(sql, params).fetchone()
            return (
                self._record(row, self._messages(connection, row["id"]))
                if row
                else None
            )

    def get_by_website_id(self, website_id: str) -> FileRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM file_records WHERE website_id = ?", (website_id,)
            ).fetchone()
            return (
                self._record(row, self._messages(connection, row["id"]))
                if row
                else None
            )

    def update_messages(
        self,
        website_id: str,
        message_ids: Sequence[int],
        source_channel_id: int | None = None,
    ) -> FileRecord:
        now = datetime.now(UTC).isoformat()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT id, source_channel_id FROM file_records WHERE website_id = ?",
                (website_id,),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(website_id)
            record_id = row["id"]
            target_channel_id = (
                source_channel_id
                if source_channel_id is not None
                else row["source_channel_id"]
            )
            self._assert_messages_available(
                connection,
                target_channel_id,
                message_ids,
                excluding_record_id=record_id,
            )
            connection.execute(
                "DELETE FROM file_messages WHERE file_record_id = ?", (record_id,)
            )
            connection.executemany(
                """INSERT INTO file_messages
                (file_record_id, position, message_id) VALUES (?, ?, ?)""",
                (
                    (record_id, position, message_id)
                    for position, message_id in enumerate(message_ids)
                ),
            )
            connection.execute(
                """UPDATE file_records
                SET source_channel_id = ?, updated_at = ? WHERE id = ?""",
                (target_channel_id, now, record_id),
            )
        record = self.get_by_website_id(website_id)
        assert record is not None
        return record

    def set_active(self, website_id: str, active: bool) -> FileRecord:
        with self._connection() as connection:
            cursor = connection.execute(
                """UPDATE file_records
                SET active = ?, updated_at = ? WHERE website_id = ?""",
                (int(active), datetime.now(UTC).isoformat(), website_id),
            )
            if cursor.rowcount == 0:
                raise FileNotFoundError(website_id)
        record = self.get_by_website_id(website_id)
        assert record is not None
        return record

    def delete(self, website_id: str) -> None:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM file_records WHERE website_id = ?", (website_id,)
            )
            if cursor.rowcount == 0:
                raise FileNotFoundError(website_id)

    def list(
        self, query: str | None = None, *, include_inactive: bool = True
    ) -> list[FileRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if query:
            clauses.append(
                "(website_id LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\')"
            )
            escaped = (
                query.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            params.extend((f"%{escaped}%", f"%{escaped}%"))
        if not include_inactive:
            clauses.append("active = 1")
        sql = "SELECT * FROM file_records"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC"
        with self._connection() as connection:
            rows = connection.execute(sql, params).fetchall()
            return [
                self._record(row, self._messages(connection, row["id"]))
                for row in rows
            ]

    # Discovery/import operations intentionally share this repository so deduplication,
    # review decisions, and registrations are committed in one SQLite database.
    def upsert_topic(self, source_chat_id: int, topic_id: int, title: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO storage_topics
                (source_chat_id, topic_id, title, discovered_at) VALUES (?, ?, ?, ?)
                ON CONFLICT(source_chat_id, topic_id) DO UPDATE SET title=excluded.title""",
                (source_chat_id, topic_id, title, now),
            )

    def list_topics(self, source_chat_id: int) -> list[StorageTopic]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM storage_topics WHERE source_chat_id=? ORDER BY topic_id",
                (source_chat_id,),
            ).fetchall()
        return [StorageTopic(row["source_chat_id"], row["topic_id"], row["title"],
                             datetime.fromisoformat(row["discovered_at"])) for row in rows]

    def add_discovered_message(
        self, *, source_chat_id: int, message_id: int, topic_id: int | None,
        topic_title: str | None, filename: str | None, caption: str | None,
        file_size: int | None, mime_type: str | None, media_group_id: str | None,
        message_date: datetime, state: str = "new",
    ) -> tuple[DiscoveredMessage, bool]:
        now = datetime.now(UTC).isoformat()
        if message_date.tzinfo is None:
            message_date = message_date.replace(tzinfo=UTC)
        with self._connection() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO discovered_messages
                (source_chat_id, message_id, topic_id, topic_title, filename, caption,
                 file_size, mime_type, media_group_id, message_date, state, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (source_chat_id, message_id, topic_id, topic_title, filename, caption,
                 file_size, mime_type, media_group_id, message_date.isoformat(), state, now),
            )
            created = cursor.rowcount == 1
            row = connection.execute(
                "SELECT * FROM discovered_messages WHERE source_chat_id=? AND message_id=?",
                (source_chat_id, message_id),
            ).fetchone()
        assert row is not None
        return self._discovered(row), created

    def get_discovered(self, discovered_id: int) -> DiscoveredMessage | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM discovered_messages WHERE id=?", (discovered_id,)
            ).fetchone()
        return self._discovered(row) if row else None

    def get_discovered_message(
        self, source_chat_id: int, message_id: int
    ) -> DiscoveredMessage | None:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT * FROM discovered_messages
                WHERE source_chat_id=? AND message_id=?""",
                (source_chat_id, message_id),
            ).fetchone()
        return self._discovered(row) if row else None

    def list_discovered(
        self, *, state: str | None = None, topic_id: int | None = None,
        media_group_id: str | None = None,
    ) -> list[DiscoveredMessage]:
        clauses: list[str] = []
        params: list[object] = []
        for column, value in (("state", state), ("topic_id", topic_id),
                              ("media_group_id", media_group_id)):
            if value is not None:
                clauses.append(f"{column}=?")
                params.append(value)
        sql = "SELECT * FROM discovered_messages"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY message_id"
        with self._connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._discovered(row) for row in rows]

    def set_discovered_state(self, discovered_id: int, state: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE discovered_messages SET state=? WHERE id=?", (state, discovered_id)
            )

    def add_match_candidate(
        self, *, discovered_message_id: int, website_file_id: str | None,
        website_title: str | None, confidence: float, status: str,
        reason: str | None = None,
    ) -> MatchCandidate:
        now = datetime.now(UTC).isoformat()
        with self._connection() as connection:
            existing = connection.execute(
                """SELECT * FROM match_candidates WHERE discovered_message_id=?
                AND website_file_id IS ?""",
                (discovered_message_id, website_file_id),
            ).fetchone()
            if existing is not None:
                return self._candidate(existing)
            connection.execute(
                """INSERT INTO match_candidates
                (discovered_message_id, website_file_id, website_title, confidence,
                 status, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (discovered_message_id, website_file_id, website_title, confidence,
                 status, reason, now),
            )
            row = connection.execute(
                """SELECT * FROM match_candidates WHERE discovered_message_id=?
                AND website_file_id IS ?""",
                (discovered_message_id, website_file_id),
            ).fetchone()
        assert row is not None
        return self._candidate(row)

    def choose_candidate_match(
        self, candidate_id: int, website_file_id: str, website_title: str,
    ) -> MatchCandidate:
        with self._connection() as connection:
            connection.execute(
                """UPDATE match_candidates SET website_file_id=?, website_title=?,
                status='ambiguous' WHERE id=? AND status NOT IN
                ('approved', 'rejected', 'ignored')""",
                (website_file_id, website_title, candidate_id),
            )
            row = connection.execute(
                "SELECT * FROM match_candidates WHERE id=?", (candidate_id,)
            ).fetchone()
        if row is None:
            raise FileNotFoundError(str(candidate_id))
        return self._candidate(row)

    def mark_related_registered(self, discovered_ids: Sequence[int]) -> None:
        if not discovered_ids:
            return
        placeholders = ",".join("?" for _ in discovered_ids)
        with self._connection() as connection:
            connection.execute(
                f"UPDATE discovered_messages SET state='registered' WHERE id IN ({placeholders})",
                list(discovered_ids),
            )
            connection.execute(
                f"""UPDATE match_candidates SET status=CASE
                WHEN status='approved' THEN 'approved' ELSE 'grouped' END,
                decided_at=COALESCE(decided_at, ?) WHERE discovered_message_id IN
                ({placeholders}) AND status NOT IN ('rejected', 'ignored')""",
                [datetime.now(UTC).isoformat(), *discovered_ids],
            )

    def get_candidate(self, candidate_id: int) -> MatchCandidate | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM match_candidates WHERE id=?", (candidate_id,)
            ).fetchone()
        return self._candidate(row) if row else None

    def list_candidates(
        self, *, statuses: Sequence[str] = ("exact", "ambiguous", "unmatched"),
        query: str | None = None, topic_id: int | None = None, limit: int = 100,
    ) -> list[MatchCandidate]:
        placeholders = ",".join("?" for _ in statuses)
        clauses = [f"mc.status IN ({placeholders})"]
        params: list[object] = list(statuses)
        if query:
            clauses.append("(dm.filename LIKE ? OR mc.website_title LIKE ?)")
            params.extend((f"%{query}%", f"%{query}%"))
        if topic_id is not None:
            clauses.append("dm.topic_id=?")
            params.append(topic_id)
        params.append(limit)
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT mc.* FROM match_candidates mc
                JOIN discovered_messages dm ON dm.id=mc.discovered_message_id
                WHERE """ + " AND ".join(clauses) +
                " ORDER BY mc.confidence DESC, mc.created_at LIMIT ?", params,
            ).fetchall()
        return [self._candidate(row) for row in rows]

    def decide_candidate(
        self, candidate_id: int, *, decision: str, admin_user_id: int,
        notes: str | None = None,
    ) -> MatchCandidate:
        now = datetime.now(UTC).isoformat()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM match_candidates WHERE id=?", (candidate_id,)
            ).fetchone()
            if row is None:
                raise FileNotFoundError(str(candidate_id))
            # Idempotent callbacks do not append conflicting audit entries.
            if row["status"] in {"approved", "rejected", "ignored"}:
                return self._candidate(row)
            connection.execute(
                "UPDATE match_candidates SET status=?, decided_at=? WHERE id=?",
                (decision, now, candidate_id),
            )
            connection.execute(
                """INSERT INTO review_decisions
                (candidate_id, admin_user_id, decision, notes, created_at)
                VALUES (?, ?, ?, ?, ?)""",
                (candidate_id, admin_user_id, decision, notes, now),
            )
            state = "registered" if decision == "approved" else decision
            connection.execute(
                "UPDATE discovered_messages SET state=? WHERE id=?",
                (state, row["discovered_message_id"]),
            )
            updated = connection.execute(
                "SELECT * FROM match_candidates WHERE id=?", (candidate_id,)
            ).fetchone()
        assert updated is not None
        return self._candidate(updated)

    def get_checkpoint(self, source_chat_id: int, topic_id: int | None) -> tuple[int, bool]:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT last_message_id, complete FROM import_checkpoints
                WHERE source_chat_id=? AND topic_id=?""",
                (source_chat_id, topic_id or 0),
            ).fetchone()
        return (row["last_message_id"], bool(row["complete"])) if row else (0, False)

    def save_checkpoint(
        self, source_chat_id: int, topic_id: int | None, last_message_id: int,
        *, complete: bool = False,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO import_checkpoints
                (source_chat_id, topic_id, last_message_id, complete, updated_at)
                VALUES (?, ?, ?, ?, ?) ON CONFLICT(source_chat_id, topic_id) DO UPDATE SET
                last_message_id=excluded.last_message_id, complete=excluded.complete,
                updated_at=excluded.updated_at""",
                (source_chat_id, topic_id or 0, last_message_id, int(complete),
                 datetime.now(UTC).isoformat()),
            )

    def set_sync_state(
        self, website_file_id: str, sheet_name: str, status: str,
        last_error: str | None = None,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO sync_state
                (website_file_id, sheet_name, status, last_error, updated_at)
                VALUES (?, ?, ?, ?, ?) ON CONFLICT(website_file_id) DO UPDATE SET
                sheet_name=excluded.sheet_name, status=excluded.status,
                last_error=excluded.last_error, updated_at=excluded.updated_at""",
                (website_file_id, sheet_name, status, last_error,
                 datetime.now(UTC).isoformat()),
            )
