"""Domain models used by the file registry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


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
