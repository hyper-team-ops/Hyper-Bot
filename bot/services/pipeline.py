"""Idempotent discovery/filter/match persistence pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from bot.database.models import CatalogEntry, MatchStatus
from bot.database.repository import SQLiteFileRepository
from bot.services.discovery import MessageFilter, ResourceMetadata, safe_filename
from bot.services.matching import FileMatcher, MatchResult


@dataclass(frozen=True, slots=True)
class PipelineResult:
    metadata: ResourceMetadata
    accepted: bool
    duplicate: bool
    match: MatchResult | None
    reason: str


class DiscoveryPipeline:
    def __init__(self, repository: SQLiteFileRepository, message_filter: MessageFilter,
                 matcher: FileMatcher, catalog: list[CatalogEntry]) -> None:
        self.repository = repository
        self.message_filter = message_filter
        self.matcher = matcher
        self.catalog = catalog

    def process(self, item: ResourceMetadata, *, dry_run: bool = False) -> PipelineResult:
        decision = self.message_filter.evaluate(item)
        match = self.matcher.match(item, self.catalog) if decision.accepted else None
        if dry_run:
            return PipelineResult(item, decision.accepted, False, match, decision.reason)
        discovered, created = self.repository.add_discovered_message(
            source_chat_id=item.source_chat_id, message_id=item.message_id,
            topic_id=item.topic_id, topic_title=item.topic_title,
            filename=safe_filename(item.filename), caption=item.caption,
            file_size=item.file_size, mime_type=item.mime_type,
            media_group_id=item.media_group_id, message_date=item.message_date,
            state="new" if decision.accepted else "ignored",
        )
        if not created:
            return PipelineResult(item, decision.accepted, True, None, "already processed")
        if not decision.accepted:
            return PipelineResult(item, False, False, None, decision.reason)
        assert match is not None
        entry = match.entry
        self.repository.add_match_candidate(
            discovered_message_id=discovered.id,
            website_file_id=entry.file_id if entry else None,
            website_title=entry.title if entry else None,
            confidence=match.confidence, status=match.status.value, reason=match.reason,
        )
        return PipelineResult(item, True, False, match, decision.reason)
