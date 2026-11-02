"""SQLite implementation of the persistent file registry."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from bot.database.models import FileRecord


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

    def _initialize(self) -> None:
        with self._connect() as connection:
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
                """
            )

    @staticmethod
    def _record(row: sqlite3.Row, message_ids: Sequence[int]) -> FileRecord:
        return FileRecord(
            id=row["id"], website_id=row["website_id"], title=row["title"],
            public_token=row["public_token"], source_channel_id=row["source_channel_id"],
            message_ids=tuple(message_ids), file_type=row["file_type"],
            description=row["description"], active=bool(row["active"]),
            strip_captions=bool(row["strip_captions"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _messages(self, connection: sqlite3.Connection, record_id: int) -> tuple[int, ...]:
        rows = connection.execute(
            "SELECT message_id FROM file_messages WHERE file_record_id = ? ORDER BY position",
            (record_id,),
        ).fetchall()
        return tuple(row["message_id"] for row in rows)

    def create(self, *, website_id: str, title: str, public_token: str,
               source_channel_id: int, message_ids: Sequence[int],
               file_type: str | None = None, description: str | None = None,
               strip_captions: bool = True) -> FileRecord:
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """INSERT INTO file_records
                    (website_id, title, public_token, source_channel_id, file_type,
                     description, strip_captions, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (website_id, title, public_token, source_channel_id, file_type,
                     description, int(strip_captions), now, now),
                )
                record_id = int(cursor.lastrowid)
                connection.executemany(
                    "INSERT INTO file_messages(file_record_id, position, message_id) VALUES (?, ?, ?)",
                    ((record_id, position, message_id) for position, message_id in enumerate(message_ids)),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateFileError("Website ID, token, or message order conflicts with an existing entry") from exc
        record = self.get_by_website_id(website_id)
        assert record is not None
        return record

    def get_by_token(self, public_token: str, *, active_only: bool = True) -> FileRecord | None:
        sql = "SELECT * FROM file_records WHERE public_token = ?"
        params: tuple[object, ...] = (public_token,)
        if active_only:
            sql += " AND active = 1"
        with self._connect() as connection:
            row = connection.execute(sql, params).fetchone()
            return self._record(row, self._messages(connection, row["id"])) if row else None

    def get_by_website_id(self, website_id: str) -> FileRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM file_records WHERE website_id = ?", (website_id,)
            ).fetchone()
            return self._record(row, self._messages(connection, row["id"])) if row else None

    def update_messages(self, website_id: str, message_ids: Sequence[int],
                        source_channel_id: int | None = None) -> FileRecord:
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, source_channel_id FROM file_records WHERE website_id = ?", (website_id,)
            ).fetchone()
            if row is None:
                raise FileNotFoundError(website_id)
            record_id = row["id"]
            connection.execute("DELETE FROM file_messages WHERE file_record_id = ?", (record_id,))
            connection.executemany(
                "INSERT INTO file_messages(file_record_id, position, message_id) VALUES (?, ?, ?)",
                ((record_id, position, message_id) for position, message_id in enumerate(message_ids)),
            )
            connection.execute(
                "UPDATE file_records SET source_channel_id = ?, updated_at = ? WHERE id = ?",
                (source_channel_id or row["source_channel_id"], now, record_id),
            )
        record = self.get_by_website_id(website_id)
        assert record is not None
        return record

    def set_active(self, website_id: str, active: bool) -> FileRecord:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE file_records SET active = ?, updated_at = ? WHERE website_id = ?",
                (int(active), datetime.now(UTC).isoformat(), website_id),
            )
            if cursor.rowcount == 0:
                raise FileNotFoundError(website_id)
        record = self.get_by_website_id(website_id)
        assert record is not None
        return record

    def delete(self, website_id: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM file_records WHERE website_id = ?", (website_id,))
            if cursor.rowcount == 0:
                raise FileNotFoundError(website_id)

    def list(self, query: str | None = None, *, include_inactive: bool = True) -> list[FileRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if query:
            clauses.append("(website_id LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\')")
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.extend((f"%{escaped}%", f"%{escaped}%"))
        if not include_inactive:
            clauses.append("active = 1")
        sql = "SELECT * FROM file_records"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC"
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
            return [self._record(row, self._messages(connection, row["id"])) for row in rows]
