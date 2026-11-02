# Hyper Team Telegram Bot

A modular Python bot for the Hyper Team at the Faculty of Informatics Engineering,
University of Aleppo. It preserves the Arabic availability, download-request,
anonymous-complaint, team-information, administrator-message, and completion-notice
flows, and adds persistent website-to-Telegram file delivery.

## How delivery works

```text
Website item (stable website_id)
        │
        ▼
Public URL containing a random token only
        │  https://t.me/HyperTeamITE_Bot?start=f_<random>
        ▼
SQLite FileRecord ──► ordered private-channel message IDs
        │
        ▼
Bot API copy_message ──► user's private chat
```

The user never receives the source channel ID or a forwarded-from attribution. Files
are delivered only in a private chat. Each message is copied, never downloaded to this
server and never forwarded. Captions are removed by default so a caption cannot
disclose storage-channel branding. The success message is sent only after Telegram
confirms that every configured message was copied.

Possession of a link is sufficient to download its resource. The links are difficult
to guess, but they are bearer links—not per-user access control.

## Requirements and installation

- Python 3.11 or newer
- A Telegram bot with a **new** BotFather token
- A private channel containing the source files

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill every required value in `.env`, then run:

```bash
python -m bot.main
# `python app.py` remains a compatible entry point.
```

The legacy source contained a real bot token. Treat it as compromised: open
`@BotFather`, use `/revoke` for that bot, generate a new token, and place only the new
value in `.env`. Do not commit `.env`; it and SQLite runtime files are ignored by Git.

## Configuration

| Variable | Purpose |
|---|---|
| `BOT_TOKEN` | New token issued by BotFather |
| `BOT_USERNAME` | Bot username without or with `@` |
| `SOURCE_CHANNEL_ID` | Private file-storage channel ID |
| `DOWNLOAD_REQUEST_CHAT_ID` | Destination for user download requests |
| `COMPLAINT_RECIPIENT_CHAT_ID` | Destination for anonymous complaints |
| `ADMIN_USER_IDS` | Comma-separated Telegram **user** IDs authorized to administer the bot |
| `DATABASE_URL` | SQLite URL, normally `sqlite:///data/hyperbot.db` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |
| `RATE_LIMIT_REQUESTS` | File deliveries allowed per user per window (default 5) |
| `RATE_LIMIT_WINDOW_SECONDS` | Sliding rate-limit window (default 60) |

Startup fails with a clear error when mandatory configuration is absent or malformed.
Administrator access is always checked against `update.effective_user.id`; channel and
group IDs do not grant administrator access.

## Configure the private storage channel

1. Create a private Telegram channel.
2. Add the bot as an administrator/member able to access channel messages. Giving it
   permission to post is not required for delivery.
3. Keep the bot in the channel for as long as registered resources must work.
4. Ensure the channel does not have protected content enabled; Telegram forbids bots
   from copying protected messages and this application does not bypass that control.
5. Set the numeric channel ID as `SOURCE_CHANNEL_ID`.
6. Upload each resource. For an album or multi-part resource, retain every message ID
   in the exact desired order.

The Bot API cannot request arbitrary historical channel history. This bot deliberately
does not pretend it can scrape old posts. Existing posts can be registered using known
message IDs, while new or forwardable posts can use the guided forwarding workflow
below. Protected channel content cannot be forwarded or copied.

## Register and manage files

All commands below require a Telegram user ID listed in `ADMIN_USER_IDS`.

```text
/file_register python-basics 451 Python Basics PDF
/file_register design-assets 500,501,502 Design Assets Album
/file_register safe-album 510,511 Safe Caption Album --keep-captions
/file_begin operating-systems Operating Systems Course
# Forward one source post, several posts, or the complete album to the bot.
/file_commit
/file_abort
/file_link python-basics
/file_update python-basics 610
/file_test python-basics
/file_disable python-basics
/file_enable python-basics
/files
/files python
/file_delete python-basics
```

`website_id` must be a stable 1–100 character ASCII identifier containing letters,
digits, `.`, `_`, or `-`. Message IDs must be positive, comma-separated, unique, and
ordered. Registration rejects duplicate website IDs and prevents one source message
from being accidentally assigned to multiple resources. Updating message mappings
keeps the same public token and website URL. Editing a source post also leaves its
public link unchanged. Disabling is preferable when existing links may need to work
again; deletion is permanent.

Registration and source-changing commands run only in a private administrator chat.
Before saving `/file_register`, `/file_update`, `/file_commit`, or re-enabling a record,
the bot performs an actual copy into that administrator chat. A mapping is not reported
as usable or persisted when the test copy fails or returns fewer messages than expected.
`/file_test` repeats that check for an existing mapping. Telegram offers no metadata-only
API that proves a message is copyable, so this visible test delivery is intentional.

The guided workflow is recommended for new posts:

1. Send `/file_begin website-id Display title` in the bot's private chat.
2. Forward the exact source-channel message, messages, or complete album to that chat.
3. Confirm the reported number of captured messages.
4. Send `/file_commit`; the bot verifies the copy and returns the stable deep link.

Only forwards whose Telegram `forward_origin` identifies the configured storage channel
are accepted. Drafts are process-local and should be committed before restarting the
bot; completed mappings are persistent in SQLite. Historical or protected posts that
cannot be forwarded can still use `/file_register` with administrator-known IDs.

Media groups must be registered only after all album messages exist, with every message
ID in display order. The secure default copies members sequentially and removes their
captions. If an administrator has verified that every original caption is safe, the
optional `--keep-captions` flag uses Telegram's `copy_messages` batch operation so the
client retains album grouping. Telegram does not allow batch copy and caption rewriting
at the same time, so these modes are intentionally explicit. The bot validates the
number of message identifiers returned by the batch API and treats a short response as
a partial failure.

## Website integration

No website source is present in this repository. The integration contract is therefore
a static, production-usable export containing only:

- stable `website_id`
- display `title`
- public `telegram_url`
- active status

Export active records as JSON or CSV:

```bash
python scripts/export_links.py > telegram-links.json
python scripts/export_links.py --format csv > telegram-links.csv
```

The export command requires only `BOT_USERNAME` and `DATABASE_URL`; it does not need the
bot token, source-channel ID, or administrator credentials. Rows are sorted by stable
`website_id` for deterministic output. Inactive records are excluded unless
`--include-inactive` is explicitly supplied.

The generated artifact never contains the channel ID, Telegram message IDs, database
primary keys, or credentials. Match the export's `website_id` to the website catalog's
stable ID and render the supplied URL:

```html
<a href="https://t.me/HyperTeamITE_Bot?start=f_x7Kp93AbCdEfGhJkLmNpQrSt"
   rel="noopener">تحميل عبر تيليغرام</a>
```

This standard `https://t.me/` link opens Telegram on desktop and mobile.

### Complete example

1. The website identifies “Python Basics” as `python-basics`.
2. An administrator uploads the PDF to the private channel, where its message ID is
   `451` (this number remains private).
3. The administrator sends `/file_register python-basics 451 Python Basics PDF`.
4. The database stores `python-basics`, a random token, the configured private channel,
   and message `451`.
5. The command returns a link such as
   `https://t.me/HyperTeamITE_Bot?start=f_x7Kp93AbCdEfGhJkLmNpQrSt`.
6. The website uses that URL. A click starts the bot, which resolves the token and calls
   `copy_message` from the private channel to the user's chat.

## Existing user and administrator flows

- `/start` without a payload displays the Arabic main menu (or admin buttons for an
  authorized administrator).
- `/help` explains navigation and `/cancel` safely exits the current conversation.
- Availability checks retain the existing HyperTeam Archive link.
- Download requests are sent to `DOWNLOAD_REQUEST_CHAT_ID` with the chat ID needed for
  a later completion notification.
- Complaints contain only the complaint text—no name, username, user ID, chat ID, or
  source message metadata.
- Admin buttons send direct messages and completion notifications after authorization.
- A deep-link `/start` works as a conversation fallback and immediately delivers its
  one specific resource in private chat only. Group attempts never copy content.
- Active conversation state takes precedence over menu text. `/start` and `/cancel`
  remain available as conversation fallbacks.

## Tests

The suite uses mocked Telegram interactions and temporary SQLite databases:

```bash
python -m unittest discover -v
# Optional pytest runner:
pip install -r requirements-dev.txt
pytest
```

It covers normal and deep-link starts, private-chat enforcement, invalid/disabled
tokens, distinct mappings, ordered and partial multi-message delivery,
copy-not-forward behavior, restart persistence, collision prevention, safe exports,
forwarded-message registration, administrator identity checks, unavailable source
messages, and existing request/anonymous-complaint/admin-message workflows. The routing
tests use the real `Application` and `ConversationHandler`, with only Telegram network
methods mocked.

## Deployment and operation

Run one polling process against the SQLite database on persistent storage. SQLite uses
WAL mode. For a live backup, prefer SQLite's online backup command rather than copying
only the main file, for example:

```bash
sqlite3 data/hyperbot.db ".backup '/secure/backups/hyperbot.db'"
```

Use a service manager such as systemd or a container restart policy, inject secrets
through the environment, and restrict OS permissions on `.env`, backups, and the data
directory. For multiple bot replicas or high write volume, implement the same repository
interface with PostgreSQL before scaling out. The in-memory rate limiter and registration
drafts are intentionally single-process; persistent file mappings remain in SQLite.

Logs intentionally record error categories rather than tokens, message text, user
identities, source IDs, or stack traces sent to users. Telegram flood-control responses
are retried once when the requested delay is at most 30 seconds. Other Telegram,
network, deleted-message, access, and protected-content failures return a generic Arabic
message without leaking internal metadata.

## Telegram limitations

- Bots cannot copy protected content or unsupported service-message types.
- Bots cannot enumerate arbitrary historical channel messages through the Bot API.
- Forward registration depends on Telegram providing a channel `forward_origin`; hidden,
  protected, copied, or non-channel messages cannot be used in that workflow.
- A deleted source post or removed channel access makes delivery unavailable.
- Telegram imposes size, media, flood-control, and API-specific restrictions.
- Sequential copying preserves configured order but Telegram ultimately controls client
  rendering and album grouping.
- If sequential delivery fails after some messages, the user is told the resource is
  partial. Retrying can duplicate the messages already copied because the Bot API has no
  atomic multi-message transaction with caption replacement.
- SQLite is appropriate for a single process; use PostgreSQL for multi-replica writes.

## Project layout

```text
app.py                         compatibility entry point
bot/
  config.py                    validated environment configuration
  main.py                      application composition
  database/                    model and SQLite repository
  handlers/                    start, legacy flows, and admin commands
  keyboards/                   Arabic menus
  middleware/                  user-ID administrator authorization
  services/                    tokens, registry, delivery, and rate limiting
  utils/                       logging setup
scripts/export_links.py        safe website link export
tests/                         automated regression tests
.env.example                   secret-free configuration template
requirements*.txt              runtime and test dependencies
```
