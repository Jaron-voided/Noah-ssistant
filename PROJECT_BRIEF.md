# Noah — Project Brief

## Goal
A Telegram-first personal assistant for one person (single-user). Noah captures anything
you send it, organizes it automatically, and acts as a bridge to Google Workspace.

## Core principle
Frictionless capture first. You should be able to fire a message at Noah without thinking
about format or category. Noah figures out what it is.

## Milestone 1 (in scope now)

Updated user decisions, 2026-10-27: use Ollama for now; support Calendar reads and
creation after explicit confirmation of each addition. Preserve existing working
features and Google authorization settings. This expands the original read-only
scope; it does not approve unrelated future milestones or declare acceptance complete.

| Feature | Detail |
|---|---|
| Capture inbox | Send text → Ollama classifies as note / link / event / task / query |
| Auto-metadata | Extracts title, URL, date, description where present |
| Persistent storage | SQLite; each capture gets an ID |
| Calendar read | `/today` and `/week` commands + NL queries hit live Google Calendar |
| Calendar creation | Dated captures offer Add / Skip; create only after explicit Add for that event |
| Auth guard | Bot only responds to the authorized Telegram user ID |
| Confirmation | Each capture echoes back what Noah understood |

## Demo additions and future features

Update, 2026-10-27: Tasks and Drive planning/implementation are now approved for
the demo, in that order. Tasks confirmed creation/default-list reads are implemented
with mocked verification; live consent/demo remains open. Drive's explicit confirmed
text/link export is also implemented with mocked verification. The digest-first
recommendation below is historical and superseded by this
Tasks-then-Drive decision. Gmail and the remaining items still require approval.

- Google Tasks: confirmed creation/default-list reads implemented; further operations planned
- Gmail read + summarize
- Gmail send (draft shown, explicit [Send / Edit / Cancel] required)
- Google Drive — confirmed text/link exports into Noah Inbox/Links or Notes implemented;
  native Docs export and broader organization remain planned
- Daily digest at 8am ET: today's events, open tasks, recent captures
- Rich natural-language retrieval (basic keyword/LIKE retrieval already exists)
- Telegram photo capture and confirmed, caption-sorted Drive upload implemented;
  automatic visual description/classification and original document uploads planned
- Webhook mode + VPS deployment

## Drive and daily-digest milestone conflict

These are the original descriptions before this reconciliation; the table preserves
their disagreement rather than silently adopting one roadmap.

| Source | Drive | Daily digest |
|---|---|---|
| `CLAUDE.md` (kept unchanged) | Milestone 2: "and Google Drive" | "milestone 2 or later" (APScheduler) |
| Previous `README.md` roadmap | Milestone 3: "Drive integration" | Milestone 3: "Daily digest" |
| Previous `PROJECT_BRIEF.md` roadmap | Milestone 2: "save long-form notes as Docs" | Milestone 3: "Daily digest at 8am ET" |

Historical recommended order (superseded for this demo by Tasks, then Drive):

1. Finish validating the current Ollama/capture/Calendar flow and confirmation gate.
2. Next milestone: a minimal digest from Calendar and SQLite captures. Establish an
   always-on runtime and reliable scheduling/delivery first; include open Google Tasks
   only after Tasks integration exists. This initial digest needs no new Google scopes.
3. Following milestone: Drive export/Docs storage, with explicit approval for the API,
   permissions, and storage behavior. It adds a separate integration and is not a
   prerequisite for a useful Calendar/capture digest.

Further Tasks operations, Gmail, scheduling and milestone numbers remain undecided.
The historical order above does not approve digest/deployment. Drive is now approved
as the next demo priority after Tasks.

## Long-term vision
- Voice notes via Telegram voice messages
- Proactive reminders from captured events
- Cross-service search ("find everything related to dentist")

## Non-goals (ever)
- Multi-user support
- Public-facing web UI
- Replacing a full task manager (Things, Todoist, etc.)
- Email triage automation without explicit user action
- Connecting to services beyond Google Workspace in v1

## Security non-goals (things we deliberately will not do)
- Broad Google OAuth scopes (e.g. `https://mail.google.com/` instead of split scopes)
- Storing raw email bodies in SQLite
- Sending any email or calendar event without explicit confirmation
