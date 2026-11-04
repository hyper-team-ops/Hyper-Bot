# Software Telegram Integration Report

Date: 2026-11-04

## Outcome

The `softwares` catalog was audited for Telegram source links and integrated with the bot registry. Every distinct, unambiguous Telegram-linked program was assigned a stable website ID, registered in SQLite, and synchronized back to the catalog with a public bot deep link and `available` status.

- Catalog rows containing a valid Telegram message link: **125**
- Distinct source messages verified through Telegram: **121**
- Active SQLite resources after registration: **121**
- Stable IDs and public links synchronized to the catalog: **121**
- JSON export records: **121**
- CSV export records: **121**
- Registration failures: **0**

Each registered resource maps to exactly one explicitly linked Telegram message. Telegram album grouping was intentionally not used during this bulk operation because neighboring items in an upload album can represent different programs.

## Quarantined catalog conflicts

Four rows reuse a Telegram message already linked by another row. They were deliberately left without a File ID, Telegram Link, or Telegram Status so the bot cannot deliver the wrong program:

| Row | Catalog title | Conflict |
|---:|---|---|
| 70 | Format.Factory | Reuses the source selected for `formatfactory` |
| 83 | Adobe Photoshop 2021 | Reuses the source selected for `Adobe.Photoshop.CC`; the source filename identifies the latter |
| 99 | Postman | Points to the source selected for `phpMyAdmin 5.2.2`; the source filename is phpMyAdmin |
| 181 | VSCodeUserSetup 1.21.0 | Reuses the source selected for `VS Code` |

These rows require corrected, distinct Telegram source links before they can be safely registered. The Postman row is a confirmed catalog-link mismatch; publishing it as-is would deliver phpMyAdmin.

## Source and mapping verification

- All 121 distinct messages were retrieved successfully using the Telegram client integration.
- No referenced message was missing or outside its linked topic.
- All messages were eligible files.
- The bot registry contains 121 unique public tokens and 121 active resources.
- A post-write reconciliation confirmed every stable catalog ID maps to the exact linked source message and expected public deep link.
- No internal Telegram chat IDs or message IDs are included by `scripts/export_links.py`.

Source accessibility was verified at registration time. End-user copyability still depends on the deployed bot retaining access to the private storage chat; Telegram provides no permanent preflight guarantee, so a real delivery test remains the definitive operational check.

## Catalog integrity

- Zero semantic changes were found in the original `softwares` columns A:F across all 181 rows (header included).
- Zero semantic changes were found in the `courses` sheet across all 331 rows (header included).
- The existing native `softwares` table was extended from six to nine columns to include `File ID`, `Telegram Link`, and `Telegram Status`.
- The four conflicting rows remain blank in all three integration columns.

## Backups

Pre-change local backups were created with owner-only permissions (`0600`):

- `reports/backups/softwares_before_telegram_bulk_2026-11-04.csv`
  - SHA-256: `fa8cc4568458fa42da4de06b57c9243e967edc1633a0eb7d9fdcb5fb9eecbd40`
- `reports/backups/courses_before_telegram_bulk_2026-11-04.csv`
  - SHA-256: `a26907ac87818b1f5e81291e0922b64117c93b9ce76be19095c173c907ead595`
- `reports/backups/hyperbot_before_software_bulk_2026-11-04.db`
  - SHA-256: `a897f3d7b0335b58b0a009a9163044100f24dfb6a624093db2897958049f746c`

A native Google Drive copy was attempted before mutation, but the connected account/project did not permit Drive copy creation. The local CSV and SQLite backups above completed before the production changes.

## Code changes

- `bot/services/google_sheets.py`
  - Added identity-checked, explicitly approved batch initialization of stable IDs.
  - Preserves existing IDs and refuses duplicate IDs or changed source/title identities.
  - Added bounded batch registration synchronization with post-write verification.
  - Kept the existing single-row methods as compatible wrappers.
- `tests/test_google_sheets.py`
  - Added batch-ID tests proving existing IDs and unrelated rows are preserved.
  - Added batch-sync tests proving only exact target cells are updated.

## Validation performed

- `python -m pytest -q`: **80 passed**
- `python -m unittest discover -q`: **80 passed**
- `python -m pip check`: **No broken requirements found**
- `git diff --check`: **passed**
- JSON link export: **121 records**
- CSV link export: **121 records**
- Live catalog/SQLite reconciliation: **passed**

## Manual follow-up

1. Correct the Telegram source links for the four quarantined rows, then register them individually through the normal reviewed workflow.
2. From an administrator account, run `/file_test <File ID>` for representative resources (and eventually each resource if full operational certification is required). This performs a real copy and confirms current bot permissions without exposing the storage chat.
3. Keep the bot as an administrator/member with permission to access and copy messages from the private storage chat.
4. Keep the SQLite database and Telegram client session on persistent storage and back them up together before deployment changes.

