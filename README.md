# Noah-ssistant

Noah is a single-user Telegram assistant for capturing notes, links, tasks,
events, and photos without switching apps. It keeps a searchable local inbox,
reads your primary Google Calendar, and can add items to Google services only
after you review and confirm each proposed write.

## What it does

- **Capture:** Ollama classifies ordinary text; SQLite stores captures with IDs.
  Search saved text with `Find <keywords>`. `/task <text>` and `/drive <text>`
  provide deterministic capture paths.
- **Calendar:** `/today`, `/week`, and supported date questions read the primary
  calendar. Relative dates use the configured local timezone (default
  `America/New_York`); ambiguous dates prompt for clarification. A dated event
  shows its resolved time and offers **Add to Calendar** or **Skip**.
  Date corrections can be standalone or full messages. `Saturday` means the next
  upcoming Saturday (including today if its event time is still ahead); `next Saturday`
  means Saturday of the following Monday–Sunday week. Month/day dates such as
  `11-12`, `11/12`, or `November 12` use the current local year, or an already explicit
  year; inferred past event dates prompt for a year. Full dates prefer `MM-DD-YYYY`;
  ISO dates remain accepted. Two-digit years mean 2000–2099. A date correction must
  agree with the established weekday; explicitly give a new weekday to change it.
  `Today` and `tonight` use the current local date; event captures still need a time
  or an explicit all-day choice. Without a time, a tonight query reads that local day.
  Common tomorrow typos are normalized. After four unsuccessful replies, Noah closes the
  clarification and asks for a complete message with an explicit date/time.
- **Google Tasks:** task captures show the proposed title and notes before
  **Add to Google Tasks** or **Skip**. `/tasks` lists up to 20 open tasks from
  the default list. Date words remain notes; task due dates and reminders are
  not set. Other task lists and task edits are not supported.
- **Google Drive:** `/drive <text or link>` previews a new plain-text file under
  `Noah Inbox/Notes` or `Noah Inbox/Links`. Noah saves the supplied link as text;
  it does not fetch the website. Existing files and sharing settings are not
  changed.
- **Photos:** Telegram photos get a preview and an explicit upload choice.
  Captions such as `meme`, `fitness`, `#travel`, or `category: travel` select a
  subfolder under `Noah Inbox/Images`. Missing or conflicting categories stay
  in `Images`. Photo bytes download only after confirmation and are uploaded
  from memory; the current limit is 10 MiB. The configured Ollama model reports
  no vision capability, so Noah does not analyze image contents.

Every Add, Save, or Upload button applies to that item only. Skip keeps the local
capture and makes no Google write. Buttons expire when Noah restarts; duplicate
taps cannot reuse a confirmation. After an uncertain network result, check the
Google service before submitting a new request.

## How it fits together

```text
Telegram → authorized handlers → Ollama classification (text only)
                           ├── SQLite capture and local search
                           ├── Google Calendar reads / confirmed event creation
                           ├── Google Tasks reads / confirmed task creation
                           └── Google Drive text or photo upload after confirmation
```

`main.py` starts Telegram long polling. Calendar, Tasks, and Drive use separate
OAuth token files. Service calls are lazy; starting Noah does not require Google
authorization. Only the explicit `auth_google.py`, `auth_tasks.py`, and
`auth_drive.py` setup commands can open browser consent.

## Setup

Requires Python 3.11+, a Telegram bot token and authorized user ID, Ollama with
the configured model, and Google Cloud API/OAuth setup for the services you use.
Install and configure privately from the project root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env  # new setup only; do not overwrite an existing file
```

Set the required Telegram values in `.env`. The default local model is `qwen3:4b`.
Start Ollama, then run:

```powershell
python main.py
```

For Google setup, enable the relevant APIs in your existing Cloud project and add
only the needed scopes under **Google Auth platform → Data Access**:

- Calendar: `https://www.googleapis.com/auth/calendar.events.owned`
- Tasks: `https://www.googleapis.com/auth/tasks`
- Drive: `https://www.googleapis.com/auth/drive.file`

Keep existing scopes and credential files. Explicitly run the corresponding
`python auth_*.py` command to consent for a service. Each service stores a
separate local token. See [DEMO.md](DEMO.md) for setup details and example
Telegram interactions.

## Privacy and storage

Captures and photo caption/category metadata are stored in the configured SQLite
database. Photo bytes are not stored in SQLite or local files. Google OAuth
client credentials and tokens are local JSON files; Calendar, Tasks, and Drive
tokens use separate paths. The application does not provide a secrets manager
or encrypt these files itself. `.env`, credentials, tokens, databases, and
SQLite sidecars are Git-ignored; private repository-local paths are checked
before use. Keep your computer account and backups protected. Do not share logs,
calendar responses, or task lists publicly.

## Tests and review

Run the mocked suite with:

```powershell
python -m pytest -q -W error::RuntimeWarning
```

The current suite has **374 passing tests**. Google and Telegram behavior is
mocked; tests use fictional data and require no live services. Independent
repository reviewers checked the Tasks, Drive, and photo additions and their
fixes. Live Telegram delivery, Google consent, and Calendar/Tasks/Drive writes
have not been verified by those tests. Ollama was checked live for model
capability metadata only; no photo was sent to it.

## Planned

Automatic image recognition requires a separately selected vision model and
remains planned. Other planned work includes native Google Docs export, richer
retrieval, voice capture, and a daily digest. Gmail features and Calendar
editing/deletion are not implemented.
