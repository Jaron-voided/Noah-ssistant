# Noah demo priorities

Approved 2026-10-27: the completed independent review, this TODO, Tasks first,
and Drive next. Gmail and other integrations remain future work.

1. **Google Tasks — demo first**
   - [x] Telegram task capture → exact preview → explicit Add to Google Tasks / Skip.
   - [x] Authorized-user guards, duplicate-tap protection, sanitized failures (mocked).
   - [x] List open tasks; separate explicit Tasks setup/token, preserving Calendar (mocked).
2. **Google Drive — next if time permits**
   - [x] Photos: recognize Telegram image, preview and confirm before download/upload.
   - [x] Images folder; explicit caption categories (meme/fitness etc.); no category guessing.
   - [x] Configured Ollama metadata checked: no vision capability; no image input sent.
   - [ ] Automatic visual sorting/description with a separately validated vision model.
   - [x] Photo authorization/duplicate/failure tests (fictional data/mocks).
   - [x] Separate completed-photo-feature review; valid documentation/test gaps fixed
         and independently verified.
   - [ ] User-run live photo rendering/upload/duplicate/restart verification.
   - [x] Save text/links as new `.txt` files in Noah Inbox/Links or Notes after Save.
   - [x] Minimum `drive.file` access, separate setup/token, confirmation, mocked checks.
   - [ ] User-run Drive consent and real save/display verification.
   - [ ] Native Docs export and richer organization (future enhancement).
3. **Future features — not part of this demo implementation**
   - [ ] Gmail read/summarize and reviewed Send/Edit/Cancel drafts; separate approval.
   - [ ] Daily digest from Calendar/captures/Tasks; scheduling/runtime approval.
   - [ ] Rich retrieval, visual analysis/document images/voice, deployment;
         Calendar edit/delete remain gated.
4. **Verification, independent review, demo**
   - [x] Existing capture/SQLite/search, relative-date Calendar reads/previews/Add/Skip
         implemented; prior independent review approved; 216 mocked tests passed.
   - [x] First public checkpoint created; private files excluded.
   - [x] Tasks independent review; no blocker, OAuth prompt/privacy fixes verified.
   - [x] Full offline suite including Drive/photos: 374 passed; live checks remain open.
   - [x] Final Drive review-fix verification and separate photo review/valid fixes.
   - [x] Exact setup/start commands and short Telegram demo script in `DEMO.md`.
   - [ ] User-run live Tasks consent, creation, listing and Calendar regression check.
   - [x] Credential/token path metadata, Git exclusions/index and one reachable
         commit's filenames checked: private files ignored/untracked, no history matches.

Implemented is not live-verified: explicit-date Telegram capture and local Ollama
were previously reported working; full live acceptance remains open. Automated
checks use fictional data and mocks and never authorize Google or create real items.
