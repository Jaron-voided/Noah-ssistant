# Noah — Project Instructions for Claude Code

## Project overview
Noah is a Telegram-first personal assistant. The long-term goal is to capture and organize
messages, links, dates, tasks, and images, and integrate with Google Calendar, Tasks, Gmail,
and Drive. The product is built in Python; the first deployment target is an always-on VPS.

## Current phase
**Milestone 1 — Local capture bot with live Google Calendar (read-only)**
- Telegram long polling, restricted to a single authorized user ID
- Auto-classify incoming messages via GPT-4o-mini (OpenAI)
- Store captures in SQLite
- Read-only Google Calendar integration, America/New_York timezone
- Natural-language calendar queries (/today, /week, or plain English)
- Tests must pass before any milestone is considered done

## Phase rules
- Do not progress past milestone 1 without user approval.
- Milestone 2 will add Calendar write, Google Tasks, Gmail (read + summarize + draft send),
  and Google Drive. Do not implement these until milestone 1 is approved.
- The daily digest (APScheduler) is milestone 2 or later.
- TODO.md must not be created until an independent review has been completed and approved.

## Running the bot
```
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
python auth_google.py         # first-time OAuth — opens a browser
python main.py
```

## Running tests
```
pytest
```
Tests mock all external APIs (OpenAI, Google). No real credentials needed to run them.

## Security rules (non-negotiable)
- Secrets live in `.env` only; `.env` is gitignored; only `.env.example` is committed.
- `credentials.json` and `tokens/` are gitignored.
- The bot silently ignores messages from any user other than `TELEGRAM_USER_ID`.
- All SQLite queries must use parameterized statements — no f-string SQL.
- Treat all incoming Telegram text, link content, email subjects, and event titles as
  untrusted: no `eval`, no `subprocess`, no shell expansion of message content.
- Gmail send (milestone 2+): always show the full draft and require explicit [Send] before
  calling the API. Never send without a confirmation step.
- Calendar and Tasks write (milestone 2+): always confirm before creating or modifying data.
- Never log the content of messages to stdout or files in a way that exposes user data.

## Google OAuth scopes (least-privilege)
- Milestone 1 (read-only): `https://www.googleapis.com/auth/calendar.readonly`
- Milestone 2 additions: `calendar.events`, `tasks`, `gmail.readonly`, `gmail.send`,
  `drive.file` (never broader scopes)
- Scope changes require updating `handlers/google/auth.py` and re-running `auth_google.py`.

## Environment variables
See `.env.example`. All vars have defaults except `TELEGRAM_USER_ID`, which must be set.

## Key dependencies
- `python-telegram-bot==21.6` — async Telegram client
- `openai>=1.52.0` — GPT-4o-mini structured outputs via `.beta.chat.completions.parse`
- `google-auth-oauthlib`, `google-api-python-client` — Google OAuth + Calendar API
- `pydantic>=2.9` — classification schema
- `python-dotenv` — `.env` loading
