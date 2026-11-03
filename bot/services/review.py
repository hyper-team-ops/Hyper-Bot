"""Administrator decisions, registration, grouping, and catalog synchronization."""

from __future__ import annotations

from dataclasses import dataclass

from bot.database.models import CatalogEntry, FileRecord
from bot.database.repository import FileNotFoundError, SQLiteFileRepository
from bot.services.deep_links import build_deep_link
from bot.services.file_registry import FileRegistry
from bot.services.google_sheets import GoogleSheetsCatalog, SheetsError


@dataclass(frozen=True, slots=True)
class ApprovalResult:
    record: FileRecord
    synchronized: bool


class ReviewService:
    def __init__(
        self, repository: SQLiteFileRepository, registry: FileRegistry,
        catalog_entries: list[CatalogEntry], bot_username: str,
        sheets: GoogleSheetsCatalog | None = None,
    ) -> None:
        self.repository = repository
        self.registry = registry
        self.catalog = {entry.file_id: entry for entry in catalog_entries}
        self.bot_username = bot_username
        self.sheets = sheets

    def sync_status(self, record: FileRecord, status: str) -> bool:
        entry = self.catalog.get(record.website_id)
        if self.sheets is None or entry is None:
            return False
        try:
            self.sheets.update_registration(
                record.website_id,
                build_deep_link(self.bot_username, record.public_token), status,
            )
            self.repository.set_sync_state(record.website_id, entry.sheet_name, status)
            return True
        except SheetsError as exc:
            self.repository.set_sync_state(
                record.website_id, entry.sheet_name, "error", type(exc).__name__
            )
            return False

    def mark_pending(self, candidate_id: int) -> bool:
        candidate = self.repository.get_candidate(candidate_id)
        if candidate is None or not candidate.website_file_id:
            return False
        entry = self.catalog.get(candidate.website_file_id)
        if self.sheets is None or entry is None or entry.telegram_status == "available":
            return False
        try:
            self.sheets.update_registration(
                entry.file_id, entry.telegram_link, "pending_review"
            )
            self.repository.set_sync_state(entry.file_id, entry.sheet_name,
                                           "pending_review")
            return True
        except SheetsError as exc:
            self.repository.set_sync_state(
                entry.file_id, entry.sheet_name, "error", type(exc).__name__
            )
            return False

    def approve(
        self, candidate_id: int, admin_user_id: int, *, file_id: str | None = None,
        discovered_ids: tuple[int, ...] | None = None,
    ) -> ApprovalResult:
        candidate = self.repository.get_candidate(candidate_id)
        if candidate is None:
            raise FileNotFoundError(str(candidate_id))
        target_id = file_id or candidate.website_file_id
        if not target_id or target_id not in self.catalog:
            raise ValueError("Choose an existing catalog File ID before approval")
        entry = self.catalog[target_id]
        if file_id and file_id != candidate.website_file_id:
            candidate = self.repository.choose_candidate_match(
                candidate_id, target_id, entry.title
            )
        item = self.repository.get_discovered(candidate.discovered_message_id)
        if item is None:
            raise FileNotFoundError(str(candidate.discovered_message_id))
        if candidate.status == "grouped":
            raise ValueError("This message was already processed as part of another resource")
        if candidate.status == "approved":
            record = self.repository.get_by_website_id(target_id)
            if record is None:
                raise RuntimeError("Approved candidate has no registry mapping")
            return ApprovalResult(record, False)
        if discovered_ids is None:
            related = (
                self.repository.list_discovered(media_group_id=item.media_group_id)
                if item.media_group_id else [item]
            )
        else:
            related = []
            for discovered_id in discovered_ids:
                related_item = self.repository.get_discovered(discovered_id)
                if related_item is None or related_item.source_chat_id != item.source_chat_id:
                    raise ValueError("Every grouped discovery ID must exist in the source chat")
                related.append(related_item)
        related.sort(key=lambda value: (value.message_date, value.message_id))
        message_ids = tuple(value.message_id for value in related)
        existing = self.repository.get_by_website_id(target_id)
        if existing is None:
            record = self.registry.register(target_id, entry.title, message_ids)
        else:
            if admin_user_id == 0:
                raise ValueError(
                    "Automatic approval never overwrites an approved mapping"
                )
            record = self.registry.replace_messages(target_id, message_ids)
            if not record.active:
                record = self.repository.set_active(target_id, True)
        self.repository.decide_candidate(
            candidate_id, decision="approved", admin_user_id=admin_user_id
        )
        self.repository.mark_related_registered(tuple(value.id for value in related))
        synchronized = self.sync_status(record, "available")
        return ApprovalResult(record, synchronized)

    def reject(self, candidate_id: int, admin_user_id: int) -> None:
        self.repository.decide_candidate(
            candidate_id, decision="rejected", admin_user_id=admin_user_id
        )

    def ignore(self, candidate_id: int, admin_user_id: int) -> None:
        self.repository.decide_candidate(
            candidate_id, decision="ignored", admin_user_id=admin_user_id
        )

    def reconsider(self, candidate_id: int) -> None:
        candidate = self.repository.get_candidate(candidate_id)
        if candidate is None:
            raise FileNotFoundError(str(candidate_id))
        with self.repository._connection() as connection:
            connection.execute(
                """UPDATE match_candidates SET status='ambiguous', decided_at=NULL
                WHERE id=?""", (candidate_id,)
            )
            connection.execute(
                "UPDATE discovered_messages SET state='new' WHERE id=?",
                (candidate.discovered_message_id,),
            )
