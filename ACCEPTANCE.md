# Noah — Acceptance and Verification

## Current approved scope

Local capture using Ollama, Google Calendar reads, and event creation only after explicit
confirmation of each addition (user decisions, 2026-10-27). Preserve existing working
features and Google authorization settings. Future features still need separate approval.

The checklist below describes acceptance requirements. Unchecked items have not been
established end to end by this documentation task; mocked test evidence is listed separately.

## Acceptance checklist

- [ ] Only `TELEGRAM_USER_ID` can use commands, capture, or Calendar callbacks; other
      users get no response and cause no processing or writes.
- [ ] Bot startup requires only Telegram token/user ID; Google credentials and Ollama
      need not be available until their respective operations are requested.
- [ ] Real Ollama classifies notes, URLs, tasks, events, and queries reliably and
      extracts correct dates/times. Each saved capture response includes type and ID.
- [ ] Concrete capture checks: "Buy milk" is a task, a bare URL is a link, a plain
      sentence without action words is a note, and "Dentist April 3rd 10am" is an event
      with the intended date/time. Resolve ambiguous dates before any live addition.
- [ ] Captures persist across a real restart and can be retrieved.
- [ ] In a fresh test database, three captures produce three rows and restarting
      retains them. Never reset the existing personal database for this check.
- [ ] `/today`, `/week`, and supported plain-English routing read the live primary
      Calendar with correct dates/times, defaulting to `America/New_York`.
- [ ] Production Calendar reads use live API data, with no `.ics`, hardcoded events,
      or sample calendar data substituted; synthetic data belongs in mocked tests.
- [ ] Dated event capture saves locally and previews the addition with Add/Skip;
      capturing alone never creates a Calendar event.
- [ ] Explicit Add creates the intended event once; Skip and expired buttons never
      create it. Unauthorized users cannot confirm an addition.
- [ ] Timed and all-day creations are accepted by Google with correct start/end dates.
- [ ] Missing/expired credentials and API/network errors are handled acceptably without
      exposing secrets or personal data. No unauthorized reauthorization or scope changes.
- [ ] `.env`, credentials, all token files (including default `token.json`), and local
      databases stay out of commits. SQL values use parameterized statements.
- [ ] Untrusted content is safely rendered, never executed, and not exposed through logs.
- [x] The unit/regression suite passes without real service credentials or live calls.

## Tests actually run

On 2026-10-27, the latest suite passed: **216 passed in 3.30s** with
`python -m pytest -q -W error::RuntimeWarning --tb=short --show-capture=no`.
Dummy process settings were supplied for all eight configuration variables; external
service calls were mocked. The earlier timeout/confirmation change finished with 78
passing tests. Before those fixes, its expanded suite reported 14 failures and
52 passes, reproducing timeout-request settings, event-loop blocking, incorrect all-day
ends, duplicate/overlapping callbacks, reply failure, and error-disclosure problems.
The authorization-guard tests passed before changes to those guards; no guard change
was required. No bot polling against Telegram, Google authorization, or live Calendar
operation was performed. Live Ollama measurements are recorded separately below.

| Test file | Count | What the tests establish |
|---|---:|---|
| `tests/test_classifier.py` | 11 | Parsing/errors, nonthinking request/timeouts, sanitized errors |
| `tests/test_capture.py` | 7 | Capture replies, preview/buttons, query delegation, errors, nonblocking classification |
| `tests/test_store.py` | 6 | SQLite save/search/recent and IDs using temporary databases |
| `tests/test_calendar.py` | 7 | Formatting, mocked list results, seven-day query interval, bounded authorized HTTP transport |
| `tests/test_calendar_write.py` | 32 | Confirmation/skip/stale paths; repeated buttons; invalid callbacks; sanitized errors/reply failures; exclusive ends; slow/cancelled insertion safety |
| `tests/test_auth_guard.py` | 16 | Authorized commands/capture; unauthorized/missing-user messages and Add/Skip callbacks never reach services or consume pending data |
| `tests/test_startup.py` | 2 | Mocked polling/loop cleanup; transport INFO request logs suppressed |
| `tests/test_dates.py` | 76 | Fixed-clock resolution; ambiguity; timestamps; boundaries/DST; preserving original timezones and ISO offsets after date replies |
| `tests/test_date_flows.py` | 25 | Grounded prompt, model-date override, clarification/cancel/expiry, midnight, query filtering/DST, all three reproduced clarification cases |
| `tests/test_google_auth.py` | 12 | No implicit OAuth/token write for missing/unusable/malformed/failed-refresh grants; explicit setup, reuse, bounded refresh, private-path guard, sanitized bot replies |
| `tests/test_private_paths.py` | 12 | SQLite sidecar/common-token ignores; unsafe/indexed overrides refused without opening contents; external paths and DB preflight |
| `tests/test_calendar_pagination.py` | 2 | Relevant timed event on page two; unchanged bounds/order; repeated-marker failure |
| `tests/test_search.py` | 8 | Supported phrases find actual fictional rows; unsupported/empty requests show help; SQL data remains parameterized |

Passing mocked tests does not mean the checklist above is complete. The suite has no
real OAuth tests or full live workflow test.
The startup test runs with the full dummy configuration; it does not independently prove
startup with missing Google credentials/settings. Classifier tests supply model responses;
they do not measure actual model classification or date extraction.

The new relative-date tests assert that ambiguous messages do not save a capture,
offer an Add button, or call Calendar before clarification. Calendar questions use
the requested local day/week rather than a fallback to today. Timed questions match
events at one instant with inclusive start/exclusive end, without guessing a duration.
Event additions still require the existing per-event confirmation.

No live Telegram, Ollama, or Google calls were made for this relative-date change.
The live Ollama measurements below belong to the earlier timeout diagnosis and do not
establish live relative-date classification or end-to-end Telegram behavior.

Each of the six repository-review fixes was preceded by failing regression checks
where practical, then relevant suites passed. Missing/unusable grants and writes were
mocked; no real credentials/tokens or personal data were read. Git private-path checks
use metadata and fictional filenames. The full run disabled `.env` loading, bytecode
and pytest-cache writes and supplied all configuration values explicitly as dummy data.
Configured private overrides remain uninspected; runtime refuses unsafe repository-local
paths before private-file access. No files were staged or committed during the fixes.

Independent repository-only verification then marked all six original findings fixed,
with no in-scope regression requiring another fix. Its isolated run passed **216 tests
in 3.14s**, with Requests/HTTPX/httplib2/browser blockers and no memory/private-content
access. Remaining limits: no live service acceptance, no hard total Google deadline,
in-flight workers cannot be forcibly cancelled, sequential update processing, and Git
preflight cannot prevent later force-staging or exclusion changes. `tests/conftest.py`
still uses `setdefault`; successful runs explicitly override all eight settings with
fictional values. Git staging still differs from this reviewed working tree.

## Live Ollama measurements (fictional data only)

Local Ollama reported version 0.34.4 and a thinking-capable `qwen3:4b`. Using the
original classifier's actual system prompt and a fictional planning event dated
2026-11-12 at 15:00 Eastern:

| Request | Wall time | Thinking characters | Other observations |
|---|---:|---:|---|
| Original payload, no `think` field | 41.02 s | 10,369 | Valid JSON; server 38.90 s, model load 2.22 s; exceeded original 30 s read timeout |
| Same payload plus `think: false` | 3.24 s | 0 | Valid JSON; server 1.10 s; model already loaded |

The first diagnostic allowed 120 seconds to observe completion; it did not run with
the original 30-second client cutoff. Timing includes client overhead, and cold/warm
loading differs, so this is diagnostic evidence rather than a controlled performance study.
`/api/show` reported only `true` in its thinking controls, but direct `think: false`
requests were accepted and empirically produced no thinking output on this installation.

The fixed Python classifier was then called with three fictional inputs:

| Input category | Wall time | Result |
|---|---:|---|
| Timed event | 5.563 s | Valid schema, expected type/date, zero thinking characters; 2.491 s model load |
| Task | 2.601 s | Valid schema, expected type, null event date, zero thinking characters |
| All-day event | 2.969 s | Valid schema, expected event type and date-only value, zero thinking characters |

Only metrics and validation booleans were printed, not generated content or reasoning.
No model was downloaded, switched, or reconfigured. These samples do not establish
accuracy for arbitrary text or latency under load.

## Remaining verification

- Live Telegram startup, commands, authorized/unauthorized behavior, and reply rendering.
- Broader Ollama classification/date accuracy, cold starts, and latency under load;
  availability and three fictional classifications were checked above.
- Live relative-date capture/query behavior through Telegram with the updated prompt
  and clarification flow; exact manual inputs are listed in `README.md`.
- Existing OAuth token grants/validity/refresh and effective local path overrides; these
  were deliberately not inspected. Source requests `calendar.events.owned` and defaults
  to `credentials.json` / `token.json` (see `README.md`).
- Live Calendar reads and explicitly confirmed inserts, including timezone/DST behavior,
  repeated clicks/retries, errors, and all-day display. Exclusive end dates and repeated
  callbacks now pass mocked regression tests; live Google acceptance remains unverified.
- Persistence across a real bot restart, comprehensive auth/escaping/logging review,
  and assurance that sensitive material is absent from tracked/staged content.

## Safe future validation procedure

1. Run the mocked suite with dummy settings and temporary databases; inspect failures
   without dumping secrets or personal data.
2. Review the unverified cases above before treating current scope as complete.
3. Live checks require a separately agreed session: reuse existing authorization and
   settings, avoid collecting personal data in tool output, and stop if reauthorization
   would be needed. `python auth_google.py` is not a prerequisite for existing users.
4. For any live creation check, show the intended test event and require explicit Add
   for that event. Never infer approval from a capture or this validation plan.
5. Record actual outcomes separately from mocked evidence; leave unperformed checks open.

Tasks, Gmail, Drive, digests, and deployment acceptance criteria must be agreed before
their implementation. The proposed roadmap in `PROJECT_BRIEF.md` is not implementation approval.
