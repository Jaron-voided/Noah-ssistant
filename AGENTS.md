# Noah — Agent Instructions

Applies throughout this repository. Read `CLAUDE.md`, `README.md`, `DESIGN.md`,
`ACCEPTANCE.md`, and `PROJECT_BRIEF.md` before changing behavior. Preserve existing
work; inspect the working tree and make only changes within the requested scope.

## Current decisions and approval gates

- User decisions (2026-10-27): use Ollama for now; support Calendar reads and
  event creation only after explicit confirmation of each addition. Preserve
  existing working features and Google authorization settings.
- Noah remains a single-user, Telegram-first Python assistant using SQLite and
  long polling, with `America/New_York` as the default timezone.
- Current scope is local capture, Calendar reads, and confirmed event additions.
  Tasks, Gmail, Drive, daily digests/APScheduler, webhooks, VPS deployment, and
  Calendar modification/deletion require separate approval. Current scope is
  not a declaration that milestone acceptance is complete.
- Do not create `TODO.md` until an independent review is completed and approved.
- Preserve the non-goals in `PROJECT_BRIEF.md`: no multi-user support, public web
  UI, full task-manager replacement, autonomous email triage, or non-Google
  service integrations in v1.

## Safety boundaries

- Silently ignore every Telegram user except `TELEGRAM_USER_ID`, including on
  callback paths. Unauthorized input must not trigger processing or writes.
- Keep secrets out of source, commits, logs, and tool output. Use `.env` or the
  documented system environment; commit only the template `.env.example`.
  Keep `credentials.json`, token files, and `tokens/` gitignored.
- Preserve Google OAuth scopes, credentials, token files, and permissions unless
  explicitly authorized to change them. Do not rerun Google authorization without
  explicit authorization. Never print secrets.
- Normal Calendar calls may reuse/refresh existing grants but must never launch
  interactive OAuth. Only the explicitly invoked `auth_google.py` setup flow may
  opt in. Private repository-local paths must be ignored and untracked before use.
- Use parameterized SQLite statements; never interpolate untrusted data into SQL.
- Treat Telegram text/captions/forwarded content, links, email subjects, and event
  titles as untrusted. Never execute them via `eval`, `exec`, `subprocess`, or
  shell expansion. Escape untrusted text for the Telegram rendering mode used.
- Never log message contents in a way that exposes user data. Do not store raw
  email bodies in SQLite.
- Require explicit **Add to Calendar** for each event; capture alone is not
  permission to create it. **Skip** must not write. Preserve this gate on callbacks.
- Future approved Calendar/Tasks modifications also require confirmation. Gmail
  send must show the full draft and require explicit **Send** before the API call;
  retain Edit/Cancel choices. Never bypass confirmation.
- Code currently requests only
  `https://www.googleapis.com/auth/calendar.events.owned`. This documents the
  requested scope, not the contents or grants of an existing token. Do not change
  it or broaden scopes. Future Tasks/Gmail/Drive scopes need explicit approval.

## Development and validation

- Use Python 3.11+ and a virtual environment; dependencies are in `requirements.txt`.
- `main.py` is the bot entry point. Configuration names/defaults and OAuth paths
  are documented in `README.md`; do not inspect or print secret values to verify them.
- Resolve capture/query dates through `dates.py` using the current configured local
  clock. Do not trust the model's date as authoritative. Ask for missing/ambiguous
  components (including DST folds/gaps) before offering Add; retain confirmation.
- Date clarifications are per-user, expire after ten minutes, and retain the original
  message's clock reference. `cancel` dismisses a clarification, not an existing event.
- Run `python -m pytest` (or `pytest`); external APIs/services must be mocked and
  tests must require no real credentials. Tests must pass before milestone completion.
- Check behavior against `ACCEPTANCE.md`: silent auth rejection, startup without
  Google credentials, classified captures with IDs, persistence, Calendar reads
  in Eastern Time, and no Calendar creation before explicit confirmation.
- `python main.py` starts live polling; `python auth_google.py` opens OAuth.
  Neither is an offline test. Prefer bounded, mocked verification.

## Historical guidance and unresolved roadmap

- Keep `CLAUDE.md` unchanged under the user's earlier instruction. Its title is
  Claude-specific; no Claude-only tooling is required. The current decisions here
  supersede its OpenAI, read-only Calendar, scope, token-path, and required-variable
  descriptions. Preserve its remaining safety and review gates.
- `auth_google.py` is the explicit, import-safe setup entry point; runtime uses
  `config.GOOGLE_TOKEN_FILE` (default `token.json`). Do not run it during automated checks.
- `PROJECT_BRIEF.md` records the conflicting Drive/digest milestone descriptions
  and a proposed order. That recommendation is not approval to implement it.
- Separate implemented behavior, mocked test evidence, and unverified live
  behavior in reports. See `ACCEPTANCE.md`; do not mark live acceptance complete
  from mocked tests alone.
