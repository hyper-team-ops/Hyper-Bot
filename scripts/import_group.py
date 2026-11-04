"""Scan Hyper Vault forum history without modifying or downloading source messages."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import os
from pathlib import Path

from bot.config import CatalogSettings, ConfigurationError, ImportSettings
from bot.database.repository import SQLiteFileRepository
from bot.services.discovery import MessageFilter, safe_filename
from bot.services.google_sheets import GoogleSheetsCatalog
from bot.services.historical_import import (
    HistoricalImporter,
    TelethonCompatibilityError,
    TelethonDependencyError,
)
from bot.services.file_registry import FileRegistry
from bot.services.matching import FileMatcher
from bot.services.pipeline import DiscoveryPipeline, PipelineResult
from bot.services.review import ReviewService


def _ids(raw: str | None) -> frozenset[int]:
    return frozenset(int(part.strip()) for part in (raw or "").split(",") if part.strip())


def _telegram_client_type():
    try:
        module = importlib.import_module("telethon")
    except ModuleNotFoundError as exc:
        if exc.name == "telethon":
            raise TelethonDependencyError(
                "Telethon is not installed; run pip install -r requirements.txt"
            ) from exc
        raise
    try:
        return module.TelegramClient
    except AttributeError as exc:
        raise TelethonCompatibilityError(
            "Installed Telethon does not expose TelegramClient"
        ) from exc


def _clean(value: object | None) -> str:
    return str(value if value is not None else "-").replace("\t", " ").replace("\n", " ")


def _preview_line(result: PipelineResult) -> str:
    item = result.metadata
    match = result.match
    entry = match.entry if match else None
    row_or_id = (
        entry.file_id or f"row:{entry.row_number} (no File ID)" if entry else "-"
    )
    status = match.status.value if match else "ignored"
    reason = match.reason if match else result.reason
    fields = (
        item.message_id, item.topic_id, item.topic_title,
        safe_filename(item.filename), item.file_size, item.mime_type,
        entry.sheet_name if entry else None, row_or_id, status, reason,
    )
    return "\t".join(_clean(value) for value in fields)


async def run(args: argparse.Namespace) -> None:
    TelegramClient = _telegram_client_type()
    settings = ImportSettings.from_env()
    settings.telethon_session_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(settings.telethon_session_path.parent, 0o700)
    except OSError:
        pass
    repository = SQLiteFileRepository(settings.database_path)
    catalog = []
    if settings.google_sheet_id and not args.no_catalog and not args.list_topics:
        catalog = GoogleSheetsCatalog(
            settings.google_sheet_id, settings.google_application_credentials
        ).load_entries()
    included = _ids(args.include_topics)
    excluded = _ids(args.exclude_topics)
    if args.topic_id:
        included = frozenset({args.topic_id})
    async with TelegramClient(str(settings.telethon_session_path),
                              settings.telegram_api_id,
                              settings.telegram_api_hash) as client:
        source_username = None
        get_entity = getattr(client, "get_entity", None)
        if get_entity is not None:
            entity = await get_entity(settings.source_chat_id)
            source_username = getattr(entity, "username", None)
        pipeline = DiscoveryPipeline(
            repository,
            MessageFilter(included_topic_ids=included, excluded_topic_ids=excluded,
                          min_file_size_bytes=args.min_size),
            FileMatcher(source_chat_id=settings.source_chat_id,
                        source_username=source_username), catalog,
        )
        importer = HistoricalImporter(client, repository, pipeline, settings.source_chat_id)
        if args.list_topics:
            for topic_id, title in (await importer.list_topics(persist=False)).items():
                print(f"{topic_id}\t{title}")
            return
        if args.preview:
            print("message_id\ttopic_id\ttopic_title\tfilename\tsize_bytes\tfile_type\t"
                  "sheet\trow_or_file_id\tmatch\treason")
        summary = await importer.scan(
            topic_id=args.topic_id, limit=args.limit, resume=args.resume,
            dry_run=args.dry_run or args.preview,
            on_result=_preview_line_and_print if args.preview else None,
        )
        print(" ".join(f"{name}={getattr(summary, name)}"
                       for name in summary.__dataclass_fields__))
        pending_service = None
        if not (args.dry_run or args.preview):
            pending_service = ReviewService(
                repository, FileRegistry(repository, settings.source_chat_id), catalog,
                settings.bot_username,
                GoogleSheetsCatalog(settings.google_sheet_id,
                                    settings.google_application_credentials)
                if (settings.google_sheet_id
                    and getattr(settings, "auto_sync_google_sheets", True)) else None,
            )
            for candidate in repository.list_candidates(limit=10000):
                pending_service.mark_pending(candidate.id)
        if (settings.auto_approve_exact_matches and not (args.dry_run or args.preview)
                and catalog):
            approved = failed = 0
            for candidate in repository.list_candidates(statuses=("exact",), limit=10000):
                # Albums are complete after a historical scan, unlike live update bursts.
                try:
                    current = repository.get_candidate(candidate.id)
                    if current is None or current.status != "exact":
                        continue
                    assert pending_service is not None
                    pending_service.approve(candidate.id, 0)
                    approved += 1
                except Exception:
                    failed += 1
            print(f"auto_approved={approved} auto_approval_failed={failed}")


def _preview_line_and_print(result: PipelineResult) -> None:
    print(_preview_line(result))


def report(args: argparse.Namespace) -> None:
    settings = CatalogSettings.from_env()
    repository = SQLiteFileRepository(settings.database_path)
    statuses = ("exact", "ambiguous", "unmatched", "ignored", "rejected")
    for candidate in repository.list_candidates(statuses=statuses, limit=args.limit or 1000):
        item = repository.get_discovered(candidate.discovered_message_id)
        print(f"{candidate.id}\t{candidate.status}\t{candidate.confidence:.2f}\t"
              f"{item.filename if item else '-'}\t{candidate.website_title or '-'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--list-topics", action="store_true")
    actions.add_argument("--dry-run", action="store_true")
    actions.add_argument("--preview", action="store_true")
    actions.add_argument("--full-scan", action="store_true")
    actions.add_argument("--resume", action="store_true")
    actions.add_argument("--report", action="store_true")
    parser.add_argument("--topic-id", type=int)
    parser.add_argument("--include-topics", help="comma-separated actual topic IDs")
    parser.add_argument("--exclude-topics", help="comma-separated actual topic IDs")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--min-size", type=int, default=1)
    parser.add_argument("--no-catalog", action="store_true",
                        help="do not access Google; all eligible files become unmatched")
    args = parser.parse_args()
    try:
        if args.report:
            report(args)
        else:
            asyncio.run(run(args))
    except ConfigurationError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc
    except (TelethonDependencyError, TelethonCompatibilityError) as exc:
        raise SystemExit(f"Telethon error: {exc}") from exc


if __name__ == "__main__":
    main()
