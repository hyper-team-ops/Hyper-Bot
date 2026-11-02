#!/usr/bin/env python3
"""Export stable website IDs and public Telegram links as JSON or CSV."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

# Support the documented direct invocation without requiring package installation.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import Settings
from bot.database.repository import SQLiteFileRepository
from bot.services.deep_links import build_deep_link


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("json", "csv"), default="json")
    parser.add_argument("--include-inactive", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    repository = SQLiteFileRepository(settings.database_path)
    rows = [
        {
            "website_id": record.website_id,
            "title": record.title,
            "telegram_url": build_deep_link(settings.bot_username, record.public_token),
            "active": record.active,
        }
        for record in repository.list(include_inactive=args.include_inactive)
    ]
    if args.format == "json":
        json.dump(rows, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return
    writer = csv.DictWriter(sys.stdout, fieldnames=("website_id", "title", "telegram_url", "active"))
    writer.writeheader()
    writer.writerows(rows)


if __name__ == "__main__":
    main()
