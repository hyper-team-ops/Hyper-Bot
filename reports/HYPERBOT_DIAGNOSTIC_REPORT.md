# HyperBot diagnostic report

Date: 2026-11-04  
Repository: local working tree at `/home/kassem_yahia/Documents/Projects/hyperBot`  
Safety posture: live Telegram and Google checks were read-only; no full import, Sheet
write, source-message mutation, unsolicited bot message, token rotation, commit, or push
was performed.

## Executive conclusion

**Production readiness: READY WITH LIMITATIONS.**

The bot code, mocked end-to-end routing, delivery, registration, persistence, and
catalog synchronization tests pass. Live read-only verification now finds the exact
Google Sheets rows for Chrome and Opera from their Telegram source URLs. Preview is
useful and does not change import state.

The remaining production blocker is catalog preparation: the live `softwares` and
`courses` tabs do not yet contain `File ID`, `Telegram Link`, or `Telegram Status`
columns. Chrome and Opera can therefore be matched to rows, but cannot be approved,
registered, or published until stable File IDs are explicitly initialized. That write
was intentionally not performed during this diagnostic.

## A. Environment

| Item | Observed value | Status |
|---|---|---|
| OS | Fedora Linux, kernel 6.19.12, x86_64, glibc 2.42 | PASS |
| Python | 3.14.3 | PASS with compatibility note |
| Shell virtual environment | `VIRTUAL_ENV` was unset; commands explicitly used `.venv/bin/python` | PASS |
| python-telegram-bot | 22.6 | PASS |
| Telethon | 1.45.0 | PASS |
| google-auth | 2.62.1 | PASS |
| google-api-python-client | 2.201.0 | PASS |
| python-dotenv | 1.2.4 | PASS; now declared in runtime requirements |
| pytest | 9.2.0 | PASS; installed from `requirements-dev.txt` |
| pytest-asyncio | 1.4.1.post1 | PASS |
| Dependency consistency | `pip check`: no broken requirements | PASS |

Python 3.14 did not expose a test or runtime incompatibility in the exercised paths.
The installed Telethon signature was verified as:

```text
GetForumTopicsRequest(peer, offset_date, offset_id, offset_topic, limit, q=None)
```

The importer correctly uses `telethon.tl.functions.messages.GetForumTopicsRequest`
with `peer=`. The system Python lacks some project/test dependencies, so project
commands must use the virtual environment.

Configuration readiness was checked without printing values:

- Telegram API ID/hash and Telethon session: configured; session is accessible.
- Source group ID: configured via the supported ID/fallback configuration.
- Google Sheet ID and service-account credential path: configured; credential file
  exists.
- Bot, destination-chat, administrator, database, and rate-limit settings: configured.
- `.env`, SQLite data, credentials, and session data are ignored by Git.
- `SOURCE_CHAT_USERNAME=Hyper_Vault` should be added to the deployment environment so
  future Bot API updates can validate public source URLs. The historical importer also
  verifies the live entity username directly.

SQLite is at the configured `DATABASE_URL` path. Its production record counts were
checked before and after preview:

```text
storage_topics 13
discovered_messages 0
match_candidates 0
import_checkpoints 0
sync_state 0
```

The counts were identical afterward.

## B. Test results

| Test area | Command | Result | Details |
|---|---|---|---|
| Dependencies | `.venv/bin/python -m pip install -r requirements-dev.txt` and `pip check` | PASS | Missing test tools installed; no broken requirements |
| Syntax/imports | `.venv/bin/python -m compileall -q bot scripts tests app.py find_group.py` | PASS | No compilation errors |
| Unit/integration suite | `.venv/bin/python -m unittest discover -v` | PASS | Initial 66/66; final suite expanded to 76 tests |
| Pytest suite | `.venv/bin/python -m pytest -q` | PASS | **76 passed in 2.74s**; final rerun 76 passed in 2.34s |
| Topic discovery | `.venv/bin/python -m scripts.import_group --list-topics` | PASS | 13 live forum topics returned |
| Historical import | `--dry-run --topic-id 84 --limit 20` | PASS | 4 processed, 3 eligible, no writes |
| Useful preview | `--preview --topic-id 84 --limit 50` | PASS | Per-message rows; 2 exact, 1 unmatched, 1 ignored |
| Second topic sample | `--dry-run --topic-id 63 --limit 20` | PASS | 20 processed; 6 exact, 2 ambiguous, 11 unmatched, 1 ignored |
| Google Sheets read | Read-only Sheets API metadata and bounded range reads | PASS | Correct workbook/tabs and source links observed; no write |
| Source URL matching | Live Sheet + live Telethon + local matcher | PASS | Chrome row 2/message 133 and Opera row 3/message 134 exact |
| Registration | Temporary SQLite and mocked copy verification tests | PASS | Stable tokens, ordering, collision prevention, restart persistence |
| File delivery | Mocked Telegram API tests | PASS | Private only, copy not forward, albums, partial failure, disabled records |
| Existing workflows | Application-level `Application.process_update` tests | PASS | Requests, anonymous complaints, admin messaging, `/start`, `/cancel` |
| Production Sheet write | Not executed | BLOCKED BY SAFETY | Requires explicit approval and backup |
| Real Bot API delivery | Not executed | MANUAL | Would message a real chat; instructions are below |

The suite includes actual PTB application routing rather than only direct callback
invocation. It verifies active complaint, request, and admin-message states consume
their text; `/start` and `/cancel` remain available; group deep links never copy;
private deep links announce success only after the mocked copy completes.

## C. Actual sanitized command outputs

### Topic discovery

Actual live output:

```text
1   General
112 Laptop Test
277 عمارة+ مدني
250 Informatics College
3   Programming (IDE & Compilers)
196 Documentation
36  Design, adobe
63  Tools
18  OS's
136 Office
126 MultiMedia
84  Browsers
89  VPN
```

`--list-topics` is now explicitly non-persistent. Topic pagination uses the response
count and Telegram cursor tuple, skips deleted topic objects, and guards against a
non-advancing cursor.

### Google Sheets read

Actual read-only observations:

```text
title=Hyper Directories
softwares: sheetId=0, rows=978, columns=26, populated data rows=180
courses:   sheetId=291500461, rows=946, columns=26, populated data rows=330
softwares headers: File Name, Size, Path, Category, Source Type, Details
courses headers:   File Name, Size, Path, Category, Source Type , Details 
rows_with_file_id=0
```

No live tab currently has the three synchronization columns. The production read used
read-only OAuth scope for this diagnostic.

### Browsers preview

Actual live preview after the fixes:

```text
message_id topic_id topic_title filename                                         size_bytes file_type                sheet     row_or_file_id       match     reason
84         -        -           -                                                -          -                        -         -                    ignored   service message
88         84       Browsers    tor-browser-windows-x86_64-portable-13.0.14.exe 104588176  application/octet-stream -         -                    unmatched no reliable catalog match
133        84       Browsers    google-chrome-134-0-6998-118_HyperTeam.zip      132978693  application/zip          softwares row:2 (no File ID) exact     exact configured-source Telegram URL match
134        84       Browsers    Opera_60.0.3255.70_x64_HyperTeam.zip             54454834  application/zip          softwares row:3 (no File ID) exact     exact configured-source Telegram URL match
processed=4 eligible=3 ignored=1 duplicates=0 exact=2 ambiguous=0 unmatched=1
```

This output is actual, not expected output. The preview did not add discoveries,
candidates, checkpoints, sync state, or topics.

### Other topic sample

Actual live dry-run output:

```text
processed=20 eligible=19 ignored=1 duplicates=0 exact=6 ambiguous=2 unmatched=11
```

### Automated suite

Actual final pytest output:

```text
........................................................................ [ 94%]
....                                                                     [100%]
76 passed in 2.74s
```

## D. Problems found and fixes

| Severity | Affected code | Root cause | Fix | Verification |
|---|---|---|---|---|
| Critical | `GoogleSheetsCatalog.load_entries` | Rows were loaded only when `File ID` already existed. The live sheet has no ID column, so the catalog was empty and every import was unmatched. | Load every named row; represent an absent ID explicitly. Such rows may be preview-matched but cannot be approved. | Live preview resolves rows 2/3; approval-without-ID regression test |
| High | `FileMatcher.match` | Matching never parsed `Source Type` Telegram URLs. | Added validated public/private Telegram message-link parsing and direct message/topic matching before all metadata scoring. | Public/private/unrelated/deep-link/YouTube/duplicate-link tests plus live Chrome/Opera verification |
| High | `_size_bytes` | `([\d.]+)` accepted malformed live data such as `2..7`, then `float()` crashed the entire preview. | Accept one valid decimal only; malformed size becomes absent secondary evidence. | Regression test and successful repeated live preview |
| High | Import synchronization control | Persistent imports constructed a live Sheets synchronizer even when `AUTO_SYNC_GOOGLE_SHEETS=false`. | Import settings now honor the switch; SQLite import/review can be separated from live Sheet writes. | Full test suite; safe rollout commands below |
| Medium | Sheet heading lookup | Exact header comparison missed trailing whitespace (`Source Type ` / `Details `) and could append duplicate synchronization headings. | Normalize header whitespace and case while preserving original cells and columns. | Header normalization and no-duplicate-column tests |
| Medium | Matching priority | Existing approved source-message mappings were not explicitly preferred over fuzzy metadata. | Added exact repository lookup and stable File ID preservation after direct URLs, before metadata. | Stable-mapping regression test |
| Medium | `--preview` | Printed summary counts only. | Added one sanitized row per message with source/topic/file/sheet/row-or-ID/status/reason. | Callback and CLI/live preview tests |
| Medium | `--list-topics` | Topic discovery defaulted to persisting topic rows and unnecessarily loaded Google catalog data. | Invoke discovery with `persist=False` and skip catalog loading. | CLI command-path regression test |
| Medium | Google API calls | No bounded client retry was requested for transient API failures. | All read/write executes now request three Google-client retries; errors remain sanitized and wrapped. | Existing permission/failure tests and full suite |
| Medium | Telethon forum compatibility | Older local implementation used the wrong generated module/parameter and weak pagination. | Preserved and validated the local uncommitted fix: correct `messages` request, `peer=`, count-aware date/ID/topic cursor, dependency-specific errors. | Telethon signature, pagination, dry-run and compatibility tests |
| Low | Development environment | pytest tools were declared but absent; python-dotenv was used by a local helper but not declared. | Installed dev requirements and declared bounded python-dotenv runtime dependency. | Version audit and `pip check` |
| Low | pytest configuration | pytest-asyncio warned that fixture loop scope was implicit. | Added `pytest.ini` with function fixture-loop scope. | Final warning-free pytest run |

No confirmed regression or bypass was found in private-only delivery, rate limiting,
token validation, administrator identity checks, anonymous complaint handling, source
caption privacy, batch-copy count validation, SQLite message ordering, or public link
exports. JSON/CSV exports contain only stable website ID, title, bot URL, and active
status—not source chat/topic/message IDs.

## E. Chrome and Opera verification

### Chrome — topic 84, message 133

- Live Sheet: `softwares` row 2, title `Chrome`, source
  `https://t.me/Hyper_Vault/84/133`.
- Live Telegram: accessible in the configured source; topic 84; ZIP filename
  `google-chrome-134-0-6998-118_HyperTeam.zip`; 132,978,693 bytes; eligible.
- Match: **EXACT**, confidence 1.0, reason `exact configured-source Telegram URL match`.
- Registration state: blocked as intended because the row has no stable File ID yet.

### Opera — topic 84, message 134

- Live Sheet: `softwares` row 3, title `Opera`, source
  `https://t.me/Hyper_Vault/84/134`.
- Live Telegram: accessible in the configured source; topic 84; ZIP filename
  `Opera_60.0.3255.70_x64_HyperTeam.zip`; 54,454,834 bytes; eligible.
- Match: **EXACT**, confidence 1.0, reason `exact configured-source Telegram URL match`.
- Registration state: blocked as intended because the row has no stable File ID yet.

The source entity ID matched the configured source ID and its live public username was
`Hyper_Vault`. Topic 84 genuinely exposes four thread messages to the authorized
Telethon account: the topic service/root message (84), Tor (88), Chrome (133), and
Opera (134). The previous count of four was not a history-pagination defect.

## F. Registration, synchronization, and delivery audit

The tested pipeline is:

```text
read-only discovery -> filter -> direct URL / stable mapping / metadata match
-> SQLite candidate -> authorized review -> ordered registry mapping
-> optional precise Sheet status/link update -> private Bot API copy
```

Key verified invariants:

- A stable File ID must identify exactly one catalog row before approval.
- Missing-ID exact source matches stay unpublished.
- Tokens are random, unique, non-sequential, and retained across source updates.
- One source message cannot be assigned to two resources.
- Album/media-group and explicitly grouped multipart ordering is deterministic.
- Failed copy verification does not persist a manual registration.
- Google failure does not roll back a successful SQLite approval; retry state is saved.
- Sheet synchronization locates the current row by File ID, so row reordering does not
  change the public mapping.
- Synchronization changes only `Telegram Link` and `Telegram Status`; `Source Type`
  (including Telegram and YouTube URLs) remains untouched.
- Delivery rejects non-private chat IDs in both handler and service layers.
- Delivery copies rather than forwards and strips captions by default.
- A batch response count must equal the requested message count.
- Sequential and batch partial failures never claim complete delivery.
- Error messages and exports do not expose the source storage identity.

## G. Outstanding issues and manual setup

1. **Back up and initialize the live Sheet columns/IDs.** This is the required next
   external write and was not authorized for this diagnostic. The generated IDs are
   stable; do not delete or regenerate them after links are published.
2. **Set `SOURCE_CHAT_USERNAME=Hyper_Vault`** in the deployment `.env` for validated
   public-link matching on future Bot API updates.
3. **Perform a private delivery smoke test manually.** The test account must open a
   generated bot link in a private bot chat. No real user was messaged automatically.
4. **Bot copyability is separate from Telethon readability.** Telethon proved messages
   133/134 exist and are eligible. The Bot API can still fail if the bot lacks source
   access or content protection is enabled. `/file_test File-ID` is the definitive
   delivery check after registration.
5. A production full scan and production Sheet synchronization were intentionally not
   run. Full-scan behavior is covered with mocks and temporary SQLite databases.
6. Sequential multipart delivery is not transactional. A retry after partial success
   can duplicate previously copied parts; Telegram provides no rollback transaction.

## H. Safe next commands

Run from the repository with the virtual environment active.

### 1. Reconfirm read-only correctness

```bash
source .venv/bin/activate
python -m scripts.import_group --preview --topic-id 84 --limit 50
python -m scripts.import_group --dry-run --topic-id 63 --limit 20
```

### 2. Back up SQLite before persistent work

```bash
mkdir -p /secure/backups
sqlite3 data/hyperbot.db ".backup '/secure/backups/hyperbot-$(date +%F).db'"
```

Also make a Google Sheets copy/export before the next step.

### 3. With explicit approval, initialize stable Sheet IDs

This writes only missing stable IDs and adds the three required columns:

```bash
python -m scripts.sync_catalog --initialize-ids
python -m scripts.import_group --preview --topic-id 84 --limit 50
```

Confirm Chrome and Opera now show stable IDs rather than `row:... (no File ID)`.

### 4. Persist discoveries without live Sheet synchronization

```bash
AUTO_SYNC_GOOGLE_SHEETS=false AUTO_APPROVE_EXACT_MATCHES=false \
  python -m scripts.import_group --full-scan --topic-id 84
python -m scripts.import_group --report --limit 100
```

This changes SQLite, so run it only after the backup and ID verification. Review in a
private administrator chat:

```text
/reviews 84
/review_next
/review_approve <candidate-id>
/file_test <File-ID>
/file_link <File-ID>
```

### 5. Synchronize only after review and copy tests

```bash
python -m scripts.sync_catalog --sync
python scripts/export_links.py > telegram-links.json
python scripts/export_links.py --format csv > telegram-links.csv
```

Inspect the export before deploying it to the website. It requires no bot token or
administrator credential and contains no internal Telegram source IDs.

### 6. Manual private delivery smoke test

1. Use `/file_link <File-ID>` as an authorized administrator.
2. Open the returned `https://t.me/HyperTeamITE_Bot?start=f_...` link in your own
   private chat with the bot.
3. Confirm the exact expected file/message collection arrives without forwarded-from
   attribution or source caption.
4. Confirm the same link in a test group refuses delivery.

## Files changed in this diagnostic

- `.env.example`
- `bot/config.py`
- `bot/database/models.py`
- `bot/database/repository.py`
- `bot/main.py`
- `bot/services/google_sheets.py`
- `bot/services/historical_import.py`
- `bot/services/matching.py`
- `bot/services/pipeline.py`
- `bot/services/review.py`
- `requirements.txt`
- `pytest.ini`
- `README.md`
- `scripts/import_group.py`
- `tests/test_discovery_matching.py`
- `tests/test_google_sheets.py`
- `tests/test_historical_import.py`
- `tests/test_import_group_cli.py`
- `tests/test_review_and_resume.py`
- `reports/HYPERBOT_DIAGNOSTIC_REPORT.md`

The pre-existing uncommitted work was retained. No reset, checkout, commit, or push was
performed.
