# Chrome-only integration test

Date: 2026-11-04  
Scope: Google Chrome only  
Result: **CONFIGURED AND SYNCHRONIZED; REAL PRIVATE DELIVERY TEST PENDING**

No Hyper Vault message was modified or downloaded. No full history import, bulk File
ID initialization, unrelated approval, unrelated registration, website change, Git
commit, or push was performed.

## 1. Verified source

Live checks were performed before any persistent mutation.

| Property | Verified value |
|---|---|
| Spreadsheet | `Hyper Directories` |
| Sheet / row | `softwares`, row 2 |
| File name | `Chrome` |
| Catalog size | `180MB` |
| Catalog path | `After Format\Browsers` |
| Catalog category | `browsers` |
| Original source URL | `https://t.me/Hyper_Vault/84/133` |
| Telegram topic | ID 84, `Browsers` |
| Telegram message | 133 |
| Telegram filename | `google-chrome-134-0-6998-118_HyperTeam.zip` |
| Telegram size | 132,978,693 bytes |
| MIME type | `application/zip` |
| Filter result | Eligible media |

Telethon resolved the configured source ID to the expected `Hyper_Vault` entity and
confirmed that message 133 belongs to topic 84. The Bot API independently confirmed
the configured source is the same supergroup and that HyperBot currently has
administrator membership. The API did not return a definitive content-protection
flag, so actual copyability remains subject to the private delivery test below.

## 2. Recoverable backups

Backups were created before the first live write:

- `reports/backups/chrome_sheet_before_2026-11-04.json` — exact values from the
  `softwares` header, Chrome row, Opera sentinel row, courses header, and courses
  sentinel row.
- `reports/backups/hyperbot_before_chrome_2026-11-04.db` — online SQLite backup made
  before Chrome registration; file mode is `0600`.

The JSON snapshot parses successfully and records the spreadsheet ID and capture time.

## 3. Google Sheets before/after

Live spreadsheet:
<https://docs.google.com/spreadsheets/d/1usavkX9vZXRqvU08dGHnrAmv5l96LfReHfEyy3nC7sc>

### Before

```text
softwares headers A:F:
File Name | Size | Path | Category | Source Type | Details

Chrome row A:E:
Chrome | 180MB | After Format\Browsers | browsers | https://t.me/Hyper_Vault/84/133

Opera row A:E:
Opera | 51.9MB | After Format\Browsers | browsers | https://t.me/Hyper_Vault/84/134
```

Columns G:I were empty and had no headers.

### After

```text
G1 = File ID
H1 = Telegram Link
I1 = Telegram Status

G2 = software-chrome
H2 = https://t.me/HyperTeamITE_Bot?start=f_FZkkjAVx32jHu5BhCsIeVRYN
I2 = available
```

The new headers were formatted to match the existing green header visually, and only
columns G:I were auto-sized. The existing native table range A:F was deliberately not
expanded because doing so would alter styling across hundreds of unrelated rows.

Post-write reconciliation returned:

```text
file_id_preserved=True
chrome_source_fields_unchanged=True
opera_row_unchanged=True
courses_sentinel_unchanged=True
headers_exact=True
chrome_status=available
```

Chrome A:E is unchanged, including the authoritative original source URL. Opera has no
File ID, Telegram Link, or Telegram Status. The `courses` tab received no new headers
or values. No other row ID was initialized.

The public CSV used by the website already exposes the new columns and current Chrome
values:

```text
File ID=software-chrome
Telegram Link=https://t.me/HyperTeamITE_Bot?start=f_FZkkjAVx32jHu5BhCsIeVRYN
Telegram Status=available
```

## 4. Stable File ID behavior

Final Chrome File ID: **`software-chrome`**

A reusable `GoogleSheetsCatalog.ensure_entry_file_id(...)` operation was added. It:

- requires explicit approval;
- validates the exact tab, row, title, and source URL immediately before writing;
- adds the synchronization headers only when missing;
- writes one target File ID cell only;
- preserves an existing target ID instead of replacing it;
- refuses duplicate IDs and row-identity drift;
- reads the result back before reporting success.

An idempotence read was executed against the live row with a different requested ID.
It returned the existing `software-chrome` value and performed no replacement.

## 5. SQLite registration

Chrome was registered through the existing architecture:

```text
Telethon metadata
  -> MessageFilter
  -> exact configured-source URL match
  -> discovered_messages
  -> exact match_candidates row
  -> ReviewService approval
  -> FileRegistry
  -> file_records + file_messages
```

Verification after reopening SQLite:

```text
match=exact
reason=exact configured-source Telegram URL match
candidate_status=approved
topic_id=84
topic_title=Browsers
website_id=software-chrome
message_ids=(133,)
active=True
source_matches=True
total_records=1
```

Final relevant table counts:

```text
file_records=1
file_messages=1
discovered_messages=1
match_candidates=1
review_decisions=1
sync_state=1
```

The source group ID came from environment configuration and is not reproduced in this
report. Topic metadata is retained in `discovered_messages`. Repeated approval returned
the same token and the registry still contained exactly one resource.

## 6. Public Telegram link

Chrome’s public download link is:

<https://t.me/HyperTeamITE_Bot?start=f_FZkkjAVx32jHu5BhCsIeVRYN>

The link contains only the bot username and a secure random public token. It does not
contain the source group, topic, or message ID.

## 7. Test results and actual outputs

### Before mutation

```text
35 passed in 1.76s
total_records=0
chrome_id_exists=False
message_133_registered=False
```

### Focused tests after adding targeted File ID support

```text
37 passed in 2.15s
```

### Final complete suite

```text
pytest:   78 passed in 2.09s
unittest: Ran 78 tests in 0.813s — OK
pip check: No broken requirements found.
git diff --check: clean
```

Coverage includes exact public/private Telegram source matching, source identity
validation, single-row Sheet writes, stable ID preservation, rejection of identity
drift, duplicate prevention, durable SQLite registration, stable tokens, deep-link
generation, private-only delivery, copy-not-forward behavior, caption stripping,
partial delivery failure, rate limiting, and actual PTB application routing.

The expected warning lines in the unittest output are produced by mocked failure tests:

```text
Telegram refused registered message copy: BadRequest
Google Sheets registration update failed: RuntimeError
```

## 8. Real Telegram delivery

**Not automatically executed.**

The bot’s administrator membership in Hyper Vault was verified, and mocked delivery
tests passed. However, the environment does not prove which configured administrator
ID is the requestor’s own private account. Sending a large ZIP to an arbitrary
configured administrator would violate the task’s safety rule.

Perform the definitive smoke test from your own private administrator conversation:

```text
/file_test software-chrome
```

Expected result:

1. Exactly `google-chrome-134-0-6998-118_HyperTeam.zip` is copied.
2. It has no forwarded-from attribution.
3. Its source caption is stripped.
4. The bot replies that source copy verification completed.

Then run:

```text
/file_link software-chrome
```

Confirm it returns the public link above. Open that link in the same private chat and
confirm the exact Chrome ZIP is copied again. A group-chat attempt must refuse delivery.

If `/file_test` fails, immediately disable publication while investigating:

```text
/file_disable software-chrome
```

This preserves the token and mapping while changing the Sheet status to unavailable.

## 9. Website integration status

The current `HyperTeam-Crawler` main branch was inspected read-only at commit
[`09415664dd030434a576e5aab432c40aa876779b`](https://github.com/hyper-team-ops/HyperTeam-Crawler/commit/09415664dd030434a576e5aab432c40aa876779b).
No website files were modified.

The website’s published CSV already contains Chrome’s `File ID`, `Telegram Link`, and
`Telegram Status`, so no credentials or server-side integration are required.
Nevertheless, the current JavaScript **does not consume them**. `makeTelegramUrl(row)`
still builds a `?text=` prefilled request from `Source Type`, and software buttons use
that generated request URL. Therefore the complete website-click-to-download flow is
not yet verified.

The separate website Codex session should make these exact changes:

1. Add a whitespace-tolerant column reader for `Telegram Link` and
   `Telegram Status`, similar to the existing `getSourceType` helper.
2. For software rows where normalized status is `available` and `Telegram Link` is a
   valid `https://t.me/HyperTeamITE_Bot?start=f_...` URL, use that link directly.
3. For missing/unavailable rows, use the existing request behavior or
   `https://t.me/HyperTeamITE_Bot?start=request` according to product requirements.
4. Do not use the private `Source Type` URL as a public download target or lookup key.
5. Change the available-software button label from “request” to a download/open-bot
   label while retaining `target="_blank"` and safe link handling.
6. Test Chrome specifically and confirm Opera still follows the unavailable fallback.
7. Add tests for available, unavailable, blank, malformed, and whitespace-padded CSV
   headers/status values.

The website refreshes its public CSV every five minutes and cache-busts fetches, so the
new row data is already consumable once the JavaScript is updated.

## 10. Files changed or created

- `bot/services/google_sheets.py`
- `tests/test_google_sheets.py`
- `reports/backups/chrome_sheet_before_2026-11-04.json`
- `reports/backups/hyperbot_before_chrome_2026-11-04.db`
- `reports/CHROME_INTEGRATION_TEST.md`

Other pre-existing uncommitted work was preserved. No commit or push was performed.

## 11. Outstanding issues and precise next step

The bot/Sheet/SQLite side is configured for Chrome only. The two remaining checks are:

1. Run `/file_test software-chrome` from the requestor’s own private administrator
   chat to prove a real Bot API copy.
2. Update `HyperTeam-Crawler/script.js` to use the available `Telegram Link` as
   described above, then click the Chrome button on the deployed site.

Until both occur, it is accurate to say Chrome is registered and synchronized, but not
that the entire website-to-real-delivery flow has passed end to end.
