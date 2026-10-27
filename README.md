# Noah

A single-user, Telegram-first Python assistant. Messages are classified with Ollama
and stored in SQLite. Noah reads Google Calendar and offers an **Add to Calendar** /
**Skip** prompt for event captures with a date; each addition requires explicit confirmation.

Current decisions (2026-10-27): use Ollama for now, preserve existing working features,
and preserve Google authorization settings. Current scope includes local capture,
Calendar reads, and confirmed event creation. This does not mark milestone acceptance complete.

`AGENTS.md` contains current agent guidance. `CLAUDE.md` remains unchanged under the
earlier user instruction; its OpenAI/read-only/configuration descriptions are historical
and superseded by these decisions. Its other safety and approval gates still apply.

## Local setup and entry point

Prerequisites: Python 3.11+, a Telegram bot token and authorized user ID, Ollama with
the configured model available, and Google Calendar authorization for Calendar operations.
The default Ollama model is `qwen3:4b`; an OpenAI API key is not used by current code.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# For a new setup only; do not overwrite an existing .env:
Copy-Item .env.example .env
# Configure privately, then start the bot:
python main.py
```

`main.py` initializes SQLite, registers command/text/callback handlers, and runs Telegram
long polling inside `asyncio.Runner`. Pending Telegram updates are dropped at startup.
Google credentials are loaded lazily on a Calendar operation, so they are not needed
just to start the bot. Ollama is contacted for text classification, not startup or direct
`/today` and `/week` commands.

## Configuration from code

`config.py` loads `.env` with python-dotenv and then reads the process environment;
existing process variables take precedence. Blank optional values use the defaults below.
These are source-code defaults, not inspected local values. Relative paths resolve from
the working directory; run from the project root.

| Variable | Requirement / code default |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Required, nonblank; no default |
| `TELEGRAM_USER_ID` | Required integer; no default |
| `OLLAMA_URL` | `http://localhost:11434` |
| `OLLAMA_MODEL` | `qwen3:4b` |
| `GOOGLE_CREDENTIALS_FILE` | `credentials.json` |
| `GOOGLE_TOKEN_FILE` | `token.json` |
| `TIMEZONE` | `America/New_York` |
| `DB_PATH` | `noah.db` |

Never print credentials, tokens, `.env` values, or personal calendar data during inspection.
Keep `.env`, credential JSON, token files, and local databases out of Git.

## Google authorization: preserve existing settings

`handlers/google/auth.py` requests exactly:

```text
https://www.googleapis.com/auth/calendar.events.owned
```

This is the scope requested by code; existing token contents, granted scopes, validity,
and effective local path overrides have not been inspected. Calendar list/insert calls
target `calendarId="primary"`. Do not replace the scope with `calendar.readonly` or
`calendar.events`, change permissions, move token files, or rerun authorization without
explicit approval.

Normal Calendar calls reuse valid credentials or refresh an existing grant at the same
configured path. Missing, malformed, unusable, or failed-refresh credentials produce a
sanitized authorization-required response. Normal operations cannot launch browser OAuth.

`python auth_google.py` is the standalone authorization helper, not the bot entry point
or an offline test. Only this explicitly invoked setup flow opts into browser authorization.
It uses the existing configured credential/token paths and unchanged scopes; it is safe
to import without starting OAuth. No real authorization flow was run during the fixes.

`private_paths.py` checks Git metadata without opening private files. Credential/token
paths inside this repository must be ignored and untracked before access; database paths
and their journal/WAL/SHM variants are checked before database initialization. Unsafe
overrides produce a sanitized setup error. Add an appropriate private Git exclusion
before using a nonstandard filename; do not move existing files or force-add them.
Paths outside this repository are outside its checkpoint; the guard is not a filesystem
permission audit. Configured `.env` overrides and actual private contents were not inspected.

## Commands and capture flow

| Input | Behavior |
|---|---|
| `/start`, `/help` | Show help |
| `/today` | Primary-calendar events for today |
| `/week` | Seven days starting at today's local midnight |
| `Find <keywords>`, `Search for <keywords>`, `Look for <keywords>` | Search saved raw text/titles, up to five matches; optional surrounding quotes |
| Other text | Ollama classification; save capture or route a query |
| Dated event capture | Save locally; offer Add to Calendar / Skip |
| Add to Calendar | Create that pending event after authorized-user confirmation |
| Skip | Discard the pending addition, retain the local capture |

Event capture and calendar questions use the current date/time from the configured
timezone (`America/New_York` by default). Ollama receives that same clock reference,
but `dates.py` resolves the date/time deterministically rather than accepting its guess.
Supported expressions include today, tomorrow, day after tomorrow, this weekday,
this/next week, ISO dates/timestamps, and month-name dates with an explicit year.

- **This Friday:** Friday of the current Monday–Sunday week. If that Friday has
  already passed, Noah asks for an exact date rather than silently choosing next week.
- **Next week:** the following Monday 00:00 through the next Monday 00:00, exclusive.
  **This week** uses the current Monday–Sunday week; `/week` stays a rolling seven days.
- **Event next week:** asks which day; a reply such as Friday selects that week's Friday.
- **All-day event:** say `all day` explicitly, or choose it when asked for a missing time.
- **Missing AM/PM, missing year/time, conflicting dates, bare/next weekdays, unsupported
  date syntax, or DST gaps/folds:** Noah asks for clarification before saving/offering Add.
  For a repeated hour, specify EDT/EST or an ISO timestamp with a UTC offset.
- **Calendar question at 5pm:** returns events active at that instant, including all-day
  events; event start is inclusive and end is exclusive. It does not invent a duration.

Previews show full resolved dates, times, and timezone; responses show resolved bounds
or the requested instant. Timed additions still default to one elapsed hour, displayed
in the preview, including across DST. Clarifications accept short follow-ups, retain
the original message's clock across midnight, and expire after ten minutes. Send `cancel`
to abandon a clarification. Unsupported language asks for an exact date/time instead
of falling back to today. Clarifying a date preserves an existing time and timezone;
timezone-only replies also work for ambiguous calendar questions and ISO event timestamps.
Supported capture search strips only the documented request prefix and surrounding
quotes. It uses the existing substring/SQLite LIKE search, not semantic retrieval or
capture date/type filtering. Unsupported retrieval questions show the supported syntax.

Pending additions and clarifications are held in memory and expire when the bot restarts.
There is no implemented Calendar edit/delete, Tasks, Gmail, Drive, digest, or image-upload flow.

## Validation and roadmap

```powershell
python -m pytest -q -W error::RuntimeWarning
```

On 2026-10-27, **216 tests passed** with dummy configuration and external calls mocked.
Coverage includes authorized/unauthorized messages and callbacks, repeated/overlapping
confirmations, all-day exclusive end dates, classifier parsing/errors, event-loop
responsiveness, SQLite, Calendar formatting, fixed-clock relative dates, clarification
flows, week/year boundaries, DST gaps/folds, and mocked polling. See `ACCEPTANCE.md`
for evidence and remaining live checks. Calendar reads fetch all result pages before
filtering, retaining the same time bounds and ordering. Calendar insertion runs in a
worker after consuming its pending confirmation. Google HTTP and grant-refresh requests
use a 30-second transport timeout, not a guaranteed total job deadline. Insertion adds
no application-level retries. Cancelling an awaiting task cannot forcibly stop its worker;
the pending addition stays consumed and an uncertain outcome requires a private Calendar
check before starting another addition. Update processing otherwise remains sequential.

The previous Ollama request used nonstreaming JSON with a 30-second timeout and no
thinking control. A fictional dated-event request took 41.02 seconds and produced a
thinking trace. The same request with `think: false` took 3.24 seconds with no trace.
The classifier now sends `think: false`, uses a 5-second connection / 120-second read
timeout, and runs in a worker thread so it does not block the Telegram event loop.
This is not a guaranteed response-time bound or a model-accuracy evaluation.

## Manual verification

1. Stop any previous bot instance with Ctrl+C. From the project root, activate the
   existing virtual environment and run `python main.py`. Keep Ollama running.
   Reuse existing Google settings; do not rerun `auth_google.py` as a routine test.
   If authorization is required, stop and decide separately whether to run setup.
2. In your private Telegram chat with Noah, send `/start`, a fictional note,
   `Buy fictional art supplies`, and `https://example.com`. Expect saved type/ID
   replies for captures. Direct `/today` and `/week` should show your Calendar in
   Telegram; check privately and do not paste personal data or raw logs into reports.
3. Send `Fictional planning session on 2026-11-12 at 15:00 America/New_York`.
   Inspect the preview, then tap **Skip**. The local capture should remain and no
   event should appear in Google Calendar. If available, use another Telegram
   account to check that commands/text get no response; do not change the allowlist.
4. **Only if you explicitly choose to create a real test event:** send a fresh
   fictional event, verify its preview, and tap **Add to Calendar**. That tap is
   confirmation for that event only. Check the primary Calendar for one event with
   the intended title and time. For an all-day check, use `All-day fictional workshop
   on 2026-11-13`, confirm only after reviewing it, and verify it occupies one day.
5. A rapid second tap, if delivered before buttons disappear, must not create another
   event or overwrite the result. Sequential and overlapping taps are also covered
   by mocked tests. After any uncertain API/reply failure, check Calendar before
   starting another addition; the same pending addition is never retried automatically.
6. Stop the bot with Ctrl+C when finished. Any test-event cleanup is a separate manual
   action in Google Calendar. No live Calendar operation was run by the agent.

For the new relative-date behavior, restart the bot to load the changes and try these
in your private Telegram chat. Choose **Skip** for capture checks unless you explicitly
want to create that event.

| Message | Expected behavior |
|---|---|
| `Fictional meeting tomorrow at 5pm` | Preview tomorrow's full date, 5pm and local timezone, then Add/Skip |
| `Fictional meeting this Friday at 5pm` | Current week's Friday, or clarification if it has passed |
| `All-day fictional workshop tomorrow` | Date-only, all-day preview and Add/Skip |
| `Fictional meeting tomorrow at 5` | Ask AM/PM; reply `5pm`, then check the preview |
| `Fictional workshop next week` | Ask day; reply `Friday`, then `all day` or `5pm` when asked |
| `What's on my calendar tomorrow?` | Tomorrow's explicit local-midnight bounds and events |
| `What's on my calendar next week?` | Next Monday–Sunday, with both boundary dates visible |
| `What's on my calendar tomorrow at 5pm?` | Resolved instant and events active then |
| `Fictional meeting 2026-11-01 at 1:30am` | Ask which repeated hour; reply `EST` or `EDT`, inspect preview, then Skip |
| `cancel` | Abandon an outstanding date clarification |

Calendar questions read your real Calendar when you run them; keep results private.
These relative-date examples have automated fixed-clock coverage; this change did not
run live Telegram, Ollama, or Google calls.

Additional review-fix checks: save a fictional note, then send `Find fictional orchid
notes`; ask `Show calendar next week at 5pm` and reply with that week's exact date;
ask `Show calendar 2026-11-01 at 1:30am` and reply `EST` or `EDT`. Reads should retain
the supplied time/zone. No Add action is needed for any of these checks.

See `DESIGN.md` for implementation details and `PROJECT_BRIEF.md` for the Drive/digest
milestone conflict and proposed order. Future integrations and deployment require approval.
