"""Validated operations around persistent file records."""

from __future__ import annotations

from collections.abc import Sequence

from bot.database.models import FileRecord
from bot.database.repository import SQLiteFileRepository
from bot.services.deep_links import generate_token, validate_website_id


def validate_message_ids(message_ids: Sequence[int]) -> tuple[int, ...]:
    values = tuple(message_ids)
    if not values or len(values) > 100:
        raise ValueError("A file requires between 1 and 100 message IDs")
    if any(not isinstance(value, int) or value <= 0 for value in values):
        raise ValueError("Message IDs must be positive integers")
    if len(set(values)) != len(values):
        raise ValueError("Message IDs cannot be repeated")
    return values


class FileRegistry:
    def __init__(self, repository: SQLiteFileRepository, source_channel_id: int) -> None:
        self.repository = repository
        self.source_channel_id = source_channel_id

    def register(self, website_id: str, title: str, message_ids: Sequence[int],
                 *, file_type: str | None = None, description: str | None = None,
                 strip_captions: bool = True) -> FileRecord:
        website_id = validate_website_id(website_id)
        title = title.strip()
        if not title or len(title) > 200:
            raise ValueError("Title must contain 1-200 characters")
        ids = validate_message_ids(message_ids)
        return self.repository.create(
            website_id=website_id, title=title, public_token=generate_token(),
            source_channel_id=self.source_channel_id, message_ids=ids,
            file_type=file_type, description=description, strip_captions=strip_captions,
        )

    def replace_messages(self, website_id: str, message_ids: Sequence[int]) -> FileRecord:
        return self.repository.update_messages(
            validate_website_id(website_id),
            validate_message_ids(message_ids),
            self.source_channel_id,
        )
