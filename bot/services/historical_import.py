"""Read-only Telethon history scanner with durable checkpoints."""

from __future__ import annotations

import asyncio
import importlib
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from bot.database.repository import SQLiteFileRepository
from bot.services.discovery import parse_telethon_message
from bot.services.pipeline import DiscoveryPipeline, PipelineResult

logger = logging.getLogger(__name__)


class TelethonDependencyError(RuntimeError):
    """Telethon is not installed in the active Python environment."""


class TelethonCompatibilityError(RuntimeError):
    """The installed Telethon package does not expose the required forum API."""


def _get_forum_topics_request() -> type[Any]:
    """Load the generated request while distinguishing absence from incompatibility."""
    try:
        telethon = importlib.import_module("telethon")
    except ModuleNotFoundError as exc:
        if exc.name == "telethon":
            raise TelethonDependencyError(
                "Telethon is not installed; run pip install -r requirements.txt"
            ) from exc
        raise
    try:
        module = importlib.import_module("telethon.tl.functions.messages")
        return module.GetForumTopicsRequest
    except (ImportError, AttributeError) as exc:
        version = getattr(telethon, "__version__", "unknown")
        raise TelethonCompatibilityError(
            "Installed Telethon " + version + " is incompatible: expected "
            "telethon.tl.functions.messages.GetForumTopicsRequest with a peer parameter"
        ) from exc


@dataclass(frozen=True, slots=True)
class ImportSummary:
    processed: int = 0
    eligible: int = 0
    ignored: int = 0
    duplicates: int = 0
    exact: int = 0
    ambiguous: int = 0
    unmatched: int = 0


class HistoricalImporter:
    def __init__(self, client: Any, repository: SQLiteFileRepository,
                 pipeline: DiscoveryPipeline, source_chat_id: int,
                 *, forum_topics_request: Callable[..., Any] | None = None) -> None:
        self.client = client
        self.repository = repository
        self.pipeline = pipeline
        self.source_chat_id = source_chat_id
        self.forum_topics_request = forum_topics_request

    async def list_topics(self, *, persist: bool = True) -> dict[int, str]:
        request_type = self.forum_topics_request or _get_forum_topics_request()
        entity = await self.client.get_input_entity(self.source_chat_id)
        topics: dict[int, str] = {}
        offset_date: datetime | None = None
        offset_id = offset_topic = 0
        fetched = 0
        previous_cursor: tuple[datetime | None, int, int] | None = None
        while True:
            response = await self.client(request_type(
                peer=entity, offset_date=offset_date, offset_id=offset_id,
                offset_topic=offset_topic, limit=100, q="",
            ))
            page = tuple(getattr(response, "topics", ()) or ())
            if not page:
                break
            fetched += len(page)
            for topic in page:
                topic_id = getattr(topic, "id", None)
                title = getattr(topic, "title", None)
                if topic_id is None or not title:
                    # ForumTopicDeleted has an ID but no usable metadata.
                    continue
                topics[int(topic_id)] = str(title)
                if persist:
                    self.repository.upsert_topic(
                        self.source_chat_id, int(topic_id), str(title)
                    )

            # Telegram documents the cursor as the final topic ID, its top-message
            # ID, and either the topic creation date or top-message date depending
            # on the response ordering mode.
            cursor_topic = next(
                (topic for topic in reversed(page)
                 if getattr(topic, "id", None) is not None
                 and getattr(topic, "top_message", None) is not None),
                None,
            )
            if cursor_topic is None:
                logger.warning("Forum topic page has no usable pagination cursor")
                break
            offset_id = int(cursor_topic.top_message)
            offset_topic = int(cursor_topic.id)
            if getattr(response, "order_by_create_date", False):
                offset_date = getattr(cursor_topic, "date", None)
            else:
                message_dates = {
                    int(message.id): getattr(message, "date", None)
                    for message in (getattr(response, "messages", ()) or ())
                    if getattr(message, "id", None) is not None
                }
                offset_date = message_dates.get(offset_id) or getattr(
                    cursor_topic, "date", None
                )
            cursor = (offset_date, offset_id, offset_topic)
            if cursor == previous_cursor:
                logger.warning("Forum topic pagination cursor did not advance")
                break
            previous_cursor = cursor
            total = getattr(response, "count", None)
            if isinstance(total, int) and fetched >= total:
                break
        return topics

    async def scan(
        self, *, topic_id: int | None = None, limit: int | None = None,
        resume: bool = False, dry_run: bool = False,
        on_result: Callable[[PipelineResult], None] | None = None,
    ) -> ImportSummary:
        topics = await self.list_topics(persist=not dry_run)
        if topic_id is not None and topic_id not in topics:
            raise ValueError(f"Unknown forum topic ID: {topic_id}")
        checkpoint, complete = self.repository.get_checkpoint(self.source_chat_id, topic_id)
        min_id = checkpoint if resume else 0
        if resume and complete:
            return ImportSummary()
        counts = {field: 0 for field in ImportSummary.__dataclass_fields__}
        entity = await self.client.get_input_entity(self.source_chat_id)
        kwargs: dict[str, Any] = {"reverse": True, "min_id": min_id}
        if topic_id is not None:
            kwargs["reply_to"] = topic_id
        if limit is not None:
            kwargs["limit"] = limit
        last_id = checkpoint
        try:
            while limit is None or counts["processed"] < limit:
                request_kwargs = dict(kwargs)
                request_kwargs["min_id"] = last_id
                if limit is not None:
                    request_kwargs["limit"] = limit - counts["processed"]
                try:
                    async for message in self.client.iter_messages(entity, **request_kwargs):
                        item = parse_telethon_message(message, self.source_chat_id, topics)
                        result = self.pipeline.process(item, dry_run=dry_run)
                        if on_result is not None:
                            on_result(result)
                        counts["processed"] += 1
                        last_id = max(last_id, item.message_id)
                        if result.duplicate:
                            counts["duplicates"] += 1
                        elif not result.accepted:
                            counts["ignored"] += 1
                        else:
                            counts["eligible"] += 1
                            if result.match is not None:
                                counts[result.match.status.value] += 1
                        if not dry_run and counts["processed"] % 100 == 0:
                            self.repository.save_checkpoint(self.source_chat_id, topic_id, last_id)
                    # A naturally exhausted iterator ends the scan. `completed` also
                    # covers an empty history without special casing.
                    break
                except Exception as exc:
                    try:
                        from telethon.errors import FloodWaitError
                    except ImportError:
                        FloodWaitError = ()  # type: ignore[assignment]
                    if not isinstance(exc, FloodWaitError):
                        raise
                    wait = max(1, int(getattr(exc, "seconds", 1)))
                    logger.warning("Telegram requested an import pause of %s seconds", wait)
                    if not dry_run:
                        self.repository.save_checkpoint(self.source_chat_id, topic_id, last_id)
                    await asyncio.sleep(wait)
        except (KeyboardInterrupt, asyncio.CancelledError):
            if not dry_run:
                self.repository.save_checkpoint(self.source_chat_id, topic_id, last_id)
            raise
        except Exception:
            if not dry_run:
                self.repository.save_checkpoint(self.source_chat_id, topic_id, last_id)
            raise
        if not dry_run:
            self.repository.save_checkpoint(self.source_chat_id, topic_id, last_id,
                                            complete=limit is None)
        return ImportSummary(**counts)
