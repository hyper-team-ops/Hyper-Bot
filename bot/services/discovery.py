"""Shared parsing and filtering for historical and live storage messages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Any


SUPPORTED_MIME_PREFIXES = ("application/", "audio/", "video/", "image/")


@dataclass(frozen=True, slots=True)
class ResourceMetadata:
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
    is_service: bool = False


@dataclass(frozen=True, slots=True)
class FilterDecision:
    accepted: bool
    reason: str


class MessageFilter:
    def __init__(
        self, *, included_topic_ids: frozenset[int] = frozenset(),
        excluded_topic_ids: frozenset[int] = frozenset(), min_file_size_bytes: int = 1,
    ) -> None:
        self.included_topic_ids = included_topic_ids
        self.excluded_topic_ids = excluded_topic_ids
        self.min_file_size_bytes = min_file_size_bytes

    def evaluate(self, item: ResourceMetadata) -> FilterDecision:
        if item.is_service:
            return FilterDecision(False, "service message")
        if item.topic_id in self.excluded_topic_ids:
            return FilterDecision(False, "excluded topic ID")
        if self.included_topic_ids and item.topic_id not in self.included_topic_ids:
            return FilterDecision(False, "topic ID is not included")
        if not item.filename and not item.mime_type:
            return FilterDecision(False, "text or empty message")
        if item.file_size is not None and item.file_size < self.min_file_size_bytes:
            return FilterDecision(False, "file is below the configured minimum size")
        if item.mime_type and not item.mime_type.casefold().startswith(SUPPORTED_MIME_PREFIXES):
            return FilterDecision(False, "unsupported media type")
        return FilterDecision(True, "eligible media")


def _topic_id(message: Any) -> int | None:
    reply = getattr(message, "reply_to", None)
    if reply is None:
        return getattr(message, "message_thread_id", None)
    return (
        getattr(reply, "reply_to_top_id", None)
        or (getattr(reply, "reply_to_msg_id", None)
            if getattr(reply, "forum_topic", False) else None)
    )


def parse_telethon_message(
    message: Any, source_chat_id: int, topics: dict[int, str] | None = None,
) -> ResourceMetadata:
    """Extract metadata without downloading media; accepts Telethon duck types in tests."""
    topics = topics or {}
    document = getattr(message, "document", None)
    file = getattr(message, "file", None)
    filename = getattr(file, "name", None)
    if not filename and document is not None:
        for attribute in getattr(document, "attributes", ()):
            candidate = getattr(attribute, "file_name", None)
            if candidate:
                filename = candidate
                break
    mime_type = getattr(file, "mime_type", None) or getattr(document, "mime_type", None)
    if mime_type is None and getattr(message, "photo", None) is not None:
        mime_type = "image/jpeg"
        filename = filename or f"photo-{message.id}.jpg"
    topic_id = _topic_id(message)
    date = getattr(message, "date", None) or datetime.now(UTC)
    return ResourceMetadata(
        source_chat_id=source_chat_id, message_id=int(message.id), topic_id=topic_id,
        topic_title=topics.get(topic_id), filename=filename,
        caption=getattr(message, "message", None),
        file_size=(getattr(file, "size", None) or getattr(document, "size", None)),
        mime_type=mime_type,
        media_group_id=(str(getattr(message, "grouped_id"))
                        if getattr(message, "grouped_id", None) is not None else None),
        message_date=date, is_service=getattr(message, "action", None) is not None,
    )


def parse_bot_message(message: Any, source_chat_id: int) -> ResourceMetadata:
    document = getattr(message, "document", None)
    media = document or getattr(message, "audio", None) or getattr(message, "video", None)
    filename = getattr(media, "file_name", None)
    mime_type = getattr(media, "mime_type", None)
    file_size = getattr(media, "file_size", None)
    if media is None and getattr(message, "photo", None):
        photo = message.photo[-1]
        filename, mime_type, file_size = f"photo-{message.message_id}.jpg", "image/jpeg", photo.file_size
    date = getattr(message, "date", None) or datetime.now(UTC)
    return ResourceMetadata(
        source_chat_id=source_chat_id, message_id=message.message_id,
        topic_id=getattr(message, "message_thread_id", None), topic_title=None,
        filename=filename, caption=getattr(message, "caption", None),
        file_size=file_size, mime_type=mime_type,
        media_group_id=getattr(message, "media_group_id", None), message_date=date,
        is_service=bool(getattr(message, "new_chat_members", None)
                        or getattr(message, "forum_topic_created", None)
                        or getattr(message, "forum_topic_edited", None)),
    )


def safe_filename(name: str | None) -> str | None:
    """Remove paths/control characters from untrusted Telegram metadata."""
    if not name:
        return None
    basename = PurePath(name.replace("\\", "/")).name
    cleaned = "".join(character for character in basename if character.isprintable())
    return cleaned[:255] or None
