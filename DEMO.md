# Noah demo

Use fictional content. Results in Telegram and Google are private; do not paste
tokens, authorization URLs, personal task lists or calendars into reports.

## Start

From the project root, stop the previous bot with Ctrl+C.
Use the same Python environment as the working bot; if using `.venv`:

```powershell
.\.venv\Scripts\Activate.ps1
python auth_tasks.py
python main.py
```

`auth_tasks.py` is a one-time explicit sign-in step, not a test. Enable the Tasks
API and review the new Tasks scope as described in README first. It creates only
a separate Tasks token. If you already authorized Tasks, starting `main.py` is
enough. Do not rerun Calendar setup or replace any existing private files.

## Three-minute Telegram script

1. `/start` — see the commands.
2. `Fictional orchid notes: use blue index cards` — local capture, then
   `Find fictional orchid notes` — retrieve it.
3. `/task Buy fictional index cards` — see title, notes, default list, no due date,
   and Add/Skip. Tap **Skip**; no Google task should be created.
4. Send `/task Buy fictional index cards` again. Only if you choose to create the
   real test task, tap **Add to Google Tasks**. Check Tasks privately for one item.
   Rapidly tapping the same confirmation twice must not create a second item.
5. `/tasks` or `List my tasks` — open items from the default list, at most 20.
6. `Task: Prepare fictional demo cards tomorrow` — deterministic task capture;
   the preview explicitly says no due date/reminder is set. Tap **Skip**.
7. `Fictional meeting tomorrow at 5pm` — the existing Calendar preview shows
   the full local date/time. Tap **Skip**. `/today` reads the real Calendar;
   use only privately if you want to demonstrate it.

Do not confirm a write while screen-sharing personal lists. Use a second Telegram
account, if available, to verify silence for `/task`, `/tasks`, text, and buttons.
Restart invalidates pending buttons. After uncertain API/reply results, check Google
Tasks before sending a fresh request. Cleanup is manual in Google Tasks.

## Evidence

The latest full offline suite passed 374 tests, including Tasks, Drive and photos.
Separate Tasks, Drive and photo reviews are complete; valid findings and follow-up
verification gaps were addressed and independently verified. No live Tasks authorization,
Tasks API call, Telegram interaction or Calendar call has been run by the agent.
Previously the user reported explicit-date Telegram capture and local Ollama working.
Drive's optional script below is implemented with mocked verification; Gmail remains future.

## Optional Drive demo

Enable the Drive API and add `https://www.googleapis.com/auth/drive.file` to the
existing project's consent Data Access list; preserve other scopes/client files.
Then stop the bot, run `python auth_drive.py` explicitly, and restart `python main.py`.

1. `/drive Fictional orchid guide https://example.com/orchids` — inspect the full
   text, `.txt` filename, and Noah Inbox/Links target. **Skip** makes no remote change.
2. Send it again; only if you choose to create the test file and any missing folders,
   tap **Save to Google Drive**. Open the returned link privately and check the text.
3. `Drive: Fictional orchid notes: water the paper flowers` — preview Notes target;
   confirm only if wanted. It creates a text file, not a native Google Doc.
4. Repeated taps on the same confirmation do not create a second save. A fresh message
   is a new capture/save. After an uncertain result, inspect Drive before resending.

Folders are app-tagged and reused, and no sharing is changed. No linked website is
fetched. These flows have not been run against live Drive by the agent.

## Photo demo (same Drive setup; no extra scope)

1. Send a fictional/test picture as a Telegram **photo**, with caption `meme`.
   The photo preview should show **Noah Inbox / Images / meme** and an Upload button.
   Tap **Skip** first: Noah must not download or upload the photo bytes.
2. Resend the photo with caption `fitness`. Only if you choose to create the real
   test file, tap **Upload photo to Drive**. Check the returned private Drive link;
   target is Images/fitness, and caption is the file description.
3. Send a photo with no caption, or with `#meme #fitness`. Preview must show Images,
   without a guessed subfolder. Tap Skip. For a custom explicit folder try caption
   `category: travel` on its own line.
4. Repeatedly tapping one Upload confirmation must not create another upload.
   A fresh photo message is a new capture. Restart expires pending confirmations.

The local model reports no vision capability; no picture analysis is claimed.
Only caption sorting is implemented. Photos are compressed Telegram JPEGs, at most
10 MiB, transferred in memory after confirmation. Photo bytes are not saved locally.
Live Telegram/Drive upload and rendering remain to be checked by you privately.
