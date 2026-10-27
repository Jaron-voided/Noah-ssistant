# Noah — Design

## Current architecture

User decisions as of 2026-10-27: Ollama for now; Calendar reads and individually confirmed
event additions. Preserve existing features and Google authorization settings.
The user subsequently approved Tasks first, Drive next, and `TODO.md` after approving
the independent review. Gmail/digests/deployment remain future work.

Tasks: `main.py` registers authorized `/task`, `/tasks`, and `task_add`/`task_skip`
callbacks through `handlers/tasks.py`. `Task:` bypasses Ollama; classified task
captures use the same preview after SQLite save. Preview uses plain text and shows
the exact title/original text, default-list target, and absence of due date/reminder.
Confirmation atomically consumes `pending_task_<capture ID>` before awaiting Google.
Skip and missing/restarted previews never insert. Worker-based calls, no insert retries,
and sanitized uncertain-outcome messages follow the Calendar safety pattern.
`handlers/google/tasks.py` uses Tasks v1, `@default`, bounded HTTP transport, and
paginated open-task reads (display limit 20). It has no edit/delete/complete methods.
`tasks_auth.py` requests only the required Tasks scope, separately from unchanged
Calendar `SCOPES`; only `auth_tasks.py` opts into browser consent. New setup uses
exclusive token creation; runtime may refresh only the separate Tasks token. Path
equality/hardlink checks reject protected-file aliases before loading. Existing bad
Tasks tokens are never replaced with new consent automatically.

Drive: authorized `/drive` and `Drive:` / `Save to Drive:` capture paths bypass
Ollama, save locally, and preview the full content/filename/folder in plain text.
`handlers/drive.py` consumes each pending save before any await, then calls
`handlers/google/drive.py` in a worker only after Save. The adapter uses Drive v3
with separate `drive.file` authorization, creates/reuses app-tagged owned folders
in My Drive (Noah Inbox → Links/Notes), and uploads original UTF-8 text with a
nonresumable multipart create. It never retrieves link contents or changes sharing.
Folder lookups paginate and reject duplicate/invalid metadata; every create uses
zero application retries. A partial multi-step save can leave folders or a file;
uncertain outcomes must be checked privately before a fresh request. `auth_drive.py`
is the sole explicit consent entry point, with separate `tokens/drive.json` and
exclusive new-file creation. It refuses aliases to Calendar/Tasks/client files.

Photos: `filters.PHOTO` routes to authorized `handlers/photos.py`. Local capture
stores type=image and caption/category metadata, not image bytes or Telegram file
IDs. In-memory pending state holds the highest-resolution Telegram file ID and the
exact proposed destination. A cached-photo reply supplies the preview. Only an
authorized Upload callback consumes it and downloads bytes with Telegram timeouts.
The 10 MiB-limited buffer is uploaded by worker to Drive as image/jpeg, under
Noah Inbox/Images and an optional explicit caption category. Buffer references are
released after the operation; there is no claim of forensic memory erasure. The
adapter never changes sharing or updates files. No visual classifier is involved;
configured Ollama metadata reports no vision support. Caption/category/uncertainty
rules and setup are documented in README. Text previews/results disable Telegram
link previews, so bot-generated previews do not request website previews.

```text
Telegram long polling
  -> main.py command/text handlers + handlers/auth_guard.py
     -> /today, /week -> handlers/google/calendar.py
     -> text -> handlers/capture.py -> llm/classifier.py (Ollama)
                -> db/store.py (SQLite capture)
                -> handlers/query.py (query routing)
                -> dated event: in-memory pending addition + Add / Skip buttons
  -> handlers/calendar_confirm.py (authorized callback)
     -> Add: handlers/google/calendar.py -> primary Calendar insert
     -> Skip / missing pending data: no Calendar write
```

## Components

- `main.py`: bot entry point; initializes SQLite and registers command, text, and
  Calendar callback handlers. Uses `asyncio.Runner` with
  `run_polling(drop_pending_updates=True, close_loop=False)` for polling lifecycle compatibility.
- `handlers/auth_guard.py`: allows only `TELEGRAM_USER_ID`. Applied to entry-point
  commands/text and Calendar callbacks. Unauthorized users receive no reply; the
  guard currently logs their numeric user ID. Silent rejection means no bot response.
- `config.py`: loads `.env` without overriding existing process variables, requires
  Telegram token and integer user ID, and supplies optional defaults. Full variable
  names/defaults are in `README.md`; no live settings were inspected.
- `llm/classifier.py`: POSTs to `{OLLAMA_URL}/api/chat`, requests JSON with `stream=False`,
  and validates the returned message using Pydantic `Classified`. Default model:
  `qwen3:4b`; `think: false`. Connection/read timeouts: 5/120 seconds. The capture
  handler runs classification via `asyncio.to_thread` to avoid blocking the event loop.
  Schema types: note/link/event/task/query/image; all-day dates use `YYYY-MM-DD`.
  The classifier accepts text only; Telegram photos use the separate confirmed
  Drive-upload flow without visual analysis. No OpenAI client is used.
- `dates.py`: shared configured-local clock, deterministic English/ISO date resolution,
  date/week bounds, and timezone validation. The classifier receives a snapshot of the
  current local date/time; model-generated event dates are replaced by validated input
  resolution. Missing/ambiguous values require clarification. DST wall times are checked
  by UTC round-trip for both folds; missing times are rejected and repeated times require
  an abbreviation/offset. Default event duration is one elapsed hour across clock changes.
- `handlers/date_clarification.py`: per-user, in-memory event/query clarification state,
  with original text/classification/clock and accumulated replies. Clarifications expire
  after ten minutes; cancel discards them. Partial events are not saved or offered for
  Calendar addition until resolved. This state never authorizes a Calendar write.
- `db/store.py`: parameterized SQLite save/search/recent operations. Query classifications
  are routed rather than stored. Captures contain raw text, title, URL, event date,
  optional JSON metadata, and creation time; the current handler does not persist the
  classifier's description, though it can include it in the pending Calendar addition.
- `handlers/capture.py`: saves captures and returns type/ID. Dated events also get
  a title/date preview and Add/Skip buttons; no Calendar API write happens on capture.
- `handlers/query.py`: resolves supported date/day/week questions through `dates.py`;
  displays explicit local range bounds, or filters a day's events at a requested instant.
  This/next week are Monday–Sunday; `/week` retains the rolling-seven-day meaning.
  All-day query filtering and time-point matching preserve exclusive event ends. Vague
  queries ask for a date/week instead of defaulting to today. Saved-note/link queries
  use Find/Search for/Look for prefixes and SQLite LIKE search (up to five results),
  without the request prefix in the search term. These requests bypass the classifier.
  Unsupported retrieval questions show help; semantic and capture date/type filtering
  are not implemented. Date/time/zone clarification merges retain supplied components,
  including original ISO clock/offset values and timezone-only replies.
- `handlers/calendar_confirm.py`: authorized Add callback creates the pending event;
  Skip does not write. Pending data is consumed before insertion or result-reply awaits.
  Repeated/overlapping Add/Skip callbacks cannot reuse it, and duplicate taps leave the
  first reply intact. Errors do not restore pending state or invite automatic retries.
  Replies use plain text and sanitized errors; Telegram reply failures do not retry
  a Calendar operation. Pending state is in `application.bot_data`, not persisted,
  so restart invalidates buttons. This is not cross-process/network idempotency.
- Calendar insertion runs in a worker after claiming the pending addition. Cancellation
  does not stop a running worker or restore pending state. Transport failures therefore
  remain potentially uncertain; check Calendar before starting a new addition. No
  application-level insertion retry is configured. PTB update processing stays sequential.
- `handlers/google/calendar.py`: lists and inserts on `primary`. Reads display times
  using `TIMEZONE` (default Eastern). Timed inserts default to one hour; naive input
  is interpreted in the configured timezone. One-day all-day events end on the next
  date (exclusive); explicit later end dates are preserved and invalid ends rejected
  before an API call. No edit/delete integration exists.

## OAuth and paths observed in source

`handlers/google/auth.py` requests only
`https://www.googleapis.com/auth/calendar.events.owned`.
It reads the configured token and refreshes existing grants if possible. Normal calls
raise a sanitized `AuthorizationRequired` instead of starting interactive OAuth.
Only `auth_google.py` opts into `get_credentials(allow_interactive=True)` and may run
desktop OAuth. Successful refresh/setup writes use the same configured token path.
Scope/path configuration is unchanged. Neither authorization nor token access occurs
at `main.py` startup. Google HTTP and grant-refresh requests use 30-second transport
timeouts; this is not a hard total execution deadline. The Calendar client follows
all pages with constant bounds/order, rejecting repeated pagination markers.

| Setting | Code default | Source |
|---|---|---|
| Client credentials path | `credentials.json` | `config.GOOGLE_CREDENTIALS_FILE` |
| Token path | `token.json` | `config.GOOGLE_TOKEN_FILE` |
| SQLite path | `noah.db` | `config.DB_PATH` |

Relative paths use the working directory. `.env`/environment overrides may differ;
their values and existing token grants were deliberately not inspected. Preserve them.
`auth_google.py` is import-safe and describes the configured token path correctly.
`private_paths.py` validates ignored/untracked Git metadata for repository-local private
paths, without opening their contents. Auth checks credential/token paths before access;
database initialization checks the DB and all three sidecars. External paths are outside
this repository's index. A Git error or unsafe in-repository override fails safely.

## Decisions and boundaries

| Decision | Current choice |
|---|---|
| Transport | Local Telegram long polling; no webhooks yet |
| Classifier | Ollama, JSON response plus Pydantic validation |
| Storage | SQLite; no raw email-body storage |
| Calendar | Read primary Calendar; create only after explicit per-event Add |
| Authorization | Preserve existing `calendar.events.owned` request and local settings |
| Timezone | `America/New_York` by default; configurable |
| Demo services | Tasks create/list and confirmed Drive text/link exports implemented |
| Future services | Gmail/digest/deployment still require approval |

The original project instructions proposed `tasks`, `gmail.readonly`, `gmail.send`, and
`drive.file` for future work. Tasks now requests its approved scope in a separate flow;
Drive now requests only `drive.file` in its own flow; Gmail scopes remain proposals.
Gmail would require full-draft preview and explicit Send/Edit/Cancel; Tasks/Calendar
modifications require confirmation. The demo priority is Tasks, then Drive; digest remains future.

## Data and input safety

The authoritative table definition is `db/schema.sql`: `captures` stores an integer ID,
type (note/link/event/task/image), raw text, nullable title/URL/event date/JSON metadata,
and a UTC creation timestamp. SQL data values use placeholders.

Treat Telegram content, link content, email subjects, and event titles as untrusted.
Never execute them or interpolate them into SQL; escape them for the output rendering
mode. Keep secrets, `.env`, credentials, tokens, and personal data out of commits and
inspection output; never log message contents in a way that exposes user data.
These are requirements, not a claim that every rendering/logging path has been audited.
`main.py` suppresses HTTPX/HTTPCore INFO request logging because Telegram request URLs
contain bot tokens. Classifier errors do not echo request details or model output.

## Evidence and known limits

See `ACCEPTANCE.md` for the 2026-10-27 mocked test result and live checks still pending.
The suite now covers authorization guards, repeated/overlapping callbacks, and all-day
end-date correctness, including leap days/year rollover. Three fictional live Ollama
classifications also passed type/date checks with no thinking output. These checks do
not establish broad model/date accuracy, existing OAuth grants, live Google payload
acceptance, or full rendering/privacy coverage. No Google authorization settings changed.
The relative-date change adds fixed-clock tests for current-time prompt grounding,
deterministic capture/query resolution, clarification follow-ups and expiry, midnight,
week/year/leap boundaries, 23/25-hour days and 167/169-hour weeks, DST gaps/folds, and
matching preview/API times across DST. The latest demo suite result is 374 passing
offline tests, including confirmed Tasks/Drive/photo flows and state isolation.
No live service calls were made for this relative-date change.

The six review fixes add mocked authorization/setup/refresh tests, component-preserving
clarification flows, Git metadata/sidecar checks, slow/cancelled insertion checks, a page-two
query match, and search against real fictional SQLite rows. Existing private contents
and live service behavior remain unverified; see `ACCEPTANCE.md`.
