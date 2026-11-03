"""Read-only Telethon history scanner with durable checkpoints."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator

from bot.database.repository import SQLiteFileRepository
from bot.services.discovery import parse_telethon_message
from bot.services.pipeline import DiscoveryPipeline, PipelineResult

logger = logging.getLogger(__name__)


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
                 pipeline: DiscoveryPipeline, source_chat_id: int) -> None:
        self.client = client
        self.repository = repository
        self.pipeline = pipeline
        self.source_chat_id = source_chat_id

    async def list_topics(self, *, persist: bool = True) -> dict[int, str]:
        try:
            from telethon.tl.functions.channels import GetForumTopicsRequest
        except ImportError as exc:
            raise RuntimeError("Telethon is required for historical import") from exc
        entity = await self.client.get_input_entity(self.source_chat_id)
        topics: dict[int, str] = {}
        offset_id = offset_topic = 0
        while True:
            response = await self.client(GetForumTopicsRequest(
                channel=entity, offset_date=None, offset_id=offset_id,
                offset_topic=offset_topic, limit=100, q="",
            ))
            page = getattr(response, "topics", ())
            for topic in page:
                topics[int(topic.id)] = topic.title
                if persist:
                    self.repository.upsert_topic(
                        self.source_chat_id, int(topic.id), topic.title
                    )
            if len(page) < 100:
                break
            offset_id = int(page[-1].top_message)
            offset_topic = int(page[-1].id)
        return topics

    async def scan(
        self, *, topic_id: int | None = None, limit: int | None = None,
        resume: bool = False, dry_run: bool = False,
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
