"""Domain models used by the file registry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class FileRecord:
    id: int
    website_id: str
    title: str
    public_token: str
    source_channel_id: int
    message_ids: tuple[int, ...]
    file_type: str | None
    description: str | None
    active: bool
    strip_captions: bool
    created_at: datetime
    updated_at: datetime

    @property
    def source_chat_id(self) -> int:
        """Preferred group-aware name for the legacy persisted column."""
        return self.source_channel_id


class MatchStatus(StrEnum):
    EXACT = "exact"
    AMBIGUOUS = "ambiguous"
    UNMATCHED = "unmatched"
    IGNORED = "ignored"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class StorageTopic:
    chat_id: int
    topic_id: int
    title: str
    discovered_at: datetime


@dataclass(frozen=True, slots=True)
class DiscoveredMessage:
    id: int
    source_chat_id: int
    message_id: int
    topic_id: int | None
    topic_title: str | None
    filename: str | None
    caption: str | None
    file_size: int | None
    mime_type: str | None
    media_group_id: str | None
    message_date: datetime
    state: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    file_id: str
    title: str
    size: str | None
    category: str | None
    source_type: str | None
    sheet_name: str
    row_number: int
    telegram_link: str | None = None
    telegram_status: str | None = None


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    id: int
    discovered_message_id: int
    website_file_id: str | None
    website_title: str | None
    confidence: float
    status: str
    reason: str | None
    created_at: datetime
    decided_at: datetime | None
