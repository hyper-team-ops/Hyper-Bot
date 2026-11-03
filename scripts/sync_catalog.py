"""Initialize catalog IDs or synchronize registered Telegram links."""

from __future__ import annotations

import argparse

from bot.config import CatalogSettings
from bot.database.repository import SQLiteFileRepository
from bot.services.deep_links import build_deep_link
from bot.services.google_sheets import GoogleSheetsCatalog


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initialize-ids", action="store_true",
                        help="explicitly add immutable File IDs to rows that lack them")
    parser.add_argument("--sync", action="store_true", help="sync all registered records")
    args = parser.parse_args()
    if not args.initialize_ids and not args.sync:
        parser.error("choose --initialize-ids and/or --sync")
    settings = CatalogSettings.from_env()
    if not settings.google_sheet_id:
        parser.error("GOOGLE_SHEET_ID is required")
    catalog = GoogleSheetsCatalog(settings.google_sheet_id,
                                  settings.google_application_credentials)
    if args.initialize_ids:
        print(f"Initialized {catalog.initialize_missing_file_ids(approved=True)} File IDs")
    if args.sync:
        repository = SQLiteFileRepository(settings.database_path)
        successes = failures = 0
        for record in repository.list():
            status = "available" if record.active else "unavailable"
            try:
                catalog.update_registration(
                    record.website_id,
                    build_deep_link(settings.bot_username, record.public_token), status,
                )
                repository.set_sync_state(record.website_id, "catalog", status)
                successes += 1
            except Exception as exc:
                repository.set_sync_state(record.website_id, "catalog", "error",
                                          type(exc).__name__)
                failures += 1
        print(f"Synchronized {successes}; failed {failures}")


if __name__ == "__main__":
    main()
