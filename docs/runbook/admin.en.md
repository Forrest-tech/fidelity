# Fidelity — administrator runbook

For whoever runs the distillation and keeps the AI tools working. Commands run in `backend/` with the
project environment (`..\.venv\Scripts\python` on Windows); set `PYTHONUTF8=1`.

## Iron rules (never break)
1. **The Dropbox source folder is read-only.** Nothing writes, moves or deletes there; every sync
   compares a before/after snapshot of the source and stores the proof in `<dest>/_sync/`.
2. **Only verified content is published.** Anything that fails or needs review goes to `_pending/`.
3. **`data/` is never committed** — it holds Dropbox credentials and work files.

## Start the application
- Double-click `启动.bat` in the project folder → browser opens <http://127.0.0.1:8000>.
  Starting it twice is harmless (it only opens the browser).
- Or: `python -m scripts.serve` (`--check` only tests the port).

## Users and roles
- **First start:** while there are no users, the sign-in page offers *Create the first administrator*.
- Create or reset a user: `python scripts/create_admin.py name@example.com --role admin|reviewer|viewer`
  (password is prompted, or taken from `FIDELITY_NEW_PASSWORD`; never on the command line).
- admin: everything · reviewer: review queue and decisions · viewer: read only.
- Sign-in is limited to 5 attempts per IP per 5 minutes; attempts are in the audit log.

## Sign-in: Google, Microsoft, GitHub, company SSO; bot check; limits
- People sign in with their email and password, or with a provider button. A button appears only when
  its credentials are set as environment variables of the server, then restart:
  `FIDELITY_OAUTH_GOOGLE_CLIENT_ID` / `_SECRET`, `FIDELITY_OAUTH_MICROSOFT_CLIENT_ID` / `_SECRET`
  (optional `FIDELITY_OAUTH_MICROSOFT_TENANT`, default `common`), `FIDELITY_OAUTH_GITHUB_CLIENT_ID` / `_SECRET`,
  `FIDELITY_OAUTH_OIDC_CLIENT_ID` / `_SECRET` / `_DISCOVERY_URL` (+ `FIDELITY_OAUTH_OIDC_LABEL`, e.g. "Okta").
- Register this redirect address with the provider: `<site>/api/v1/auth/oauth/<google|microsoft|github|oidc>/callback`.
  Behind a proxy set `FIDELITY_PUBLIC_URL` (e.g. `https://fidelity.example.com`).
- Invitation only: a provider sign-in works when a Fidelity user with the same email exists (add them under
  Users). To let a whole company domain in as viewers, set `FIDELITY_OAUTH_ALLOWED_DOMAINS=example.com`.
  Only addresses the provider has verified are accepted; provider tokens are not stored.
- Bot check (ALTCHA, runs on this server, nothing to click) protects sign-in and first-run set-up. It works
  on plain-HTTP office addresses too. `FIDELITY_CAPTCHA=off` only for scripted set-ups.
- Limits: 5 wrong passwords per address per 5 minutes, 10 per account per 15 minutes (then HTTP 429 with
  Retry-After); 300 sign-in calls per address per minute (`FIDELITY_AUTH_CALLS_PER_MINUTE`).
- Forgotten password: Users → the person → Set password. The last active administrator cannot be demoted
  or switched off.

## Dropbox access
**In the web interface (recommended):** Settings → **Cloud storage** (administrators). For each access
(*Read* for sources, *Write* for output folders) enter the App key, click Connect, allow in Dropbox and
paste the code. The connection is saved on this server; nothing to copy between machines.

Two app roles, both stored in `data/dropbox_auth.json`:
- **reader** (read-only scopes) — used for the source and for read-only copies.
- **writer** — used only for the destination; the guarded writer refuses any path outside it.

Re-authorise (e.g. after a scope change): `python -m app.distill.dropbox_io auth --app-key <key> --role reader --read-only`
(or `--role writer`). Follow the link, paste the code.

## Google Drive
Settings → Cloud storage → **Google Drive** (administrators), with Google's standard OAuth 2.0 flow:
1. Google Cloud Console: create or pick a project; enable the **Google Drive API**; OAuth consent screen
   (Internal for Workspace, or External with yourself as a test user).
2. Credentials → OAuth client ID → **Web application**; add the *Authorised redirect URI* the page shows
   (e.g. `http://localhost:8000/api/v1/storage/google/callback` — open the app with the same host name).
3. Paste the client ID and secret into the page, save, then **Connect** read access (scope `drive.readonly`)
   and write access (scope `drive`, used only for output folders). Tokens stay on the server
   (`data/google_auth.json`).
Use a Drive folder link (`https://drive.google.com/drive/folders/…`) as source or output in Cloud sync.
Google Docs, Sheets and Slides are exported to .docx, .xlsx and .pptx and distilled like Office files;
deleting on Drive moves items to the trash. Dropbox and Google Drive can be mixed (e.g. Drive → Dropbox).
Reference: developers.google.com/identity/protocols/oauth2/web-server and developers.google.com/drive/api.

## Distil and publish
**In the web interface** (reviewer or admin): **Sources → Dropbox sync**. Paste the source folder's
shared link and an output folder's shared link, keep **Dry run** ticked for the first run, start, and
follow progress, the per-file results and the log under *Recent runs*. Untick Dry run to publish. An
administrator can roll a published run back from the same place. It runs exactly the command below.

**From the command line:**
```
python -m app.distill.sync --source-link <source shared link> --dest-link <destination shared link> --dry-run
python -m app.distill.sync --source-link <…> --dest-link <…>
```
- `--dry-run` distils and verifies, uploads nothing — always run it first on a new folder.
- Unchanged files are skipped (ledger); `--force` re-distils everything; `--only NAME` limits by file name.
- Output is staged in `<dest>_staging`, checked, then promoted; previous versions go to `<dest>_archive`.
- **Rollback a run**: `python -m app.distill.sync --source-link <…> --dest-link <…> --rollback <RUN>`
  (the run id is printed at the end of each sync — "undo with: … --rollback <RUN>"; the run's
  manifest is `data/work/publish/publish-<RUN>.json`).
- Protected (encrypted) files are listed, not distilled; `--publish-protected-metadata` publishes a
  metadata-only entry for them.
- Read the run summary: PASS / REVIEW / FAIL / SKIP per file, duplicates, unsupported files.

## Review queue
In the web app (reviewer or admin): **Overview → Needs attention** and **Documents** (filter by result)
list documents that did not pass; the **Review** page shows source and Markdown side by side. Scans whose
two OCR engines disagree, drawings without a title block, and any failed check land here; on Dropbox
they are under `<dest>/_pending/`, never in the trusted tree.

## OCR (scans and images)
- Engines: RapidOCR (pip) and **Tesseract 5** (installed separately; on Windows the UB Mannheim build in
  `C:\Program Files\Tesseract-OCR`, found automatically).
- RapidOCR's English model is downloaded once, pinned and hash-checked: `python scripts/fetch_ocr_models.py`
  (into `data/models/`).
- Benchmark: `python scripts/ocr_benchmark.py --synthetic --out <dir>` or `--pdf <text PDF> --pages 1,5 --out <dir>`.

## Glossary (OCR correction)
Rebuild after a large publish so it learns new terms (it reads only `auto_verified` files):
1. Copy the published library locally with the **reader** role (example with rclone):
   `rclone copy dbx:/Transfer_Md data/work/transfer_md_snapshot --filter "- _*/**" --filter "+ *.md" --filter "- *"`
2. `python -m app.distill.glossary build ../data/work/transfer_md_snapshot` → `data/glossary.json`.

## Adapter packs (Grok skill and the others)
Regenerate whenever the library changes noticeably, or when `adapters/house_rules.yaml` is edited:
1. Refresh the local library copy (as above; for the production library copy `Md_Library`).
2. `python -m app.adapters.build --library ../data/work/transfer_md_snapshot`
3. Read `adapters/dist/build-report.json`: **starting_points_missing** lists entries in
   `house_rules.yaml` the library does not hold — fix or remove them.
4. Install:
   - **Grok**: Skills → open `au-compliance-kb` → replace its content with `adapters/dist/grok/au-compliance-kb.md`.
   - **Claude**: Settings → Capabilities → Skills → upload `adapters/dist/claude/au-compliance-kb/` (zipped).
   - **Codex / Gemini CLI**: copy `AGENTS.md` / `GEMINI.md` into the synced knowledge-base root.
5. Ask one known question (e.g. riser heights, D3D14) to confirm the pack works.

Owner facts (dates, jurisdiction rules, starting points) live in `adapters/house_rules.yaml`; library
facts (editions, drafts, counts) are generated — never type them by hand.

## Wrong-answer reports (weekly)
1. Copy `<logs>/_error_reports/` locally with the reader role.
2. `python scripts/collect_error_reports.py --reports <local copy>` → `docs/acceptance/regression.json`.
3. For each `reported` entry: check the source page; set `confirmed` (fix the cause, fill `expected`) or
   `rejected`. Confirmed entries join the question bank.

## Token cost
`python scripts/measure_tokens.py --library <local copy> --out ../docs/benchmarks/token-cost` — file
sizes, listing cost, share inside the 10k–30k target.

## Docker (recommended on the Mac and on a server)
Keeps the Mac's own environment untouched: everything runs in one container, data in two Docker volumes.
1. Install Docker Desktop. In the project folder: `cp deploy/docker/fidelity.env.example deploy/docker/fidelity.env`
   and set the PostgreSQL password (or delete the two database lines to use SQLite inside the container).
2. PostgreSQL on the Mac: create the role and database (see "Server database"). The container reaches the Mac
   as `host.docker.internal`; Docker Desktop forwards that to the Mac itself, so a PostgreSQL that listens on
   localhost normally works. If the connection is refused, set `listen_addresses = '*'` and allow
   `192.168.65.0/24` (Docker Desktop's network) in `pg_hba.conf` with `scram-sha-256`.
3. `docker compose up -d --build` — then open <http://127.0.0.1:8000>, create the first administrator, and
   connect Dropbox / Google Drive under Settings → Cloud storage. Update: `git pull` and the same command.
   Logs: `docker compose logs -f`. Stop: `docker compose down` (data stays in the volumes).
4. Optional local correction model: install Ollama **natively** on the Mac (it uses the Apple GPU, which a
   container cannot) and uncomment `FIDELITY_LLM_URL=http://host.docker.internal:11434` in the env file.
In Docker the OCR engines are RapidOCR and Tesseract (CPU). Apple Vision needs macOS itself, so it is only
available with the native install below; on the benchmark it ranked third, so Docker loses little accuracy.

## Mac mini (Phase 6)
1. `./deploy/mac/install.sh` — installs Homebrew packages (Python 3.11, Tesseract, Node, Ollama), the
   Python environment (locked versions when `deploy/mac/requirements-macos.lock` is present — download it
   from the CI artifact `macos-benchmarks-and-lock`), the Phase 6 extras (Apple Vision, PaddleOCR, pix2tex),
   the local correction model, the web interface, and a launchd service that starts at login and restarts
   if it stops. Safe to run again. `--check` only lists prerequisites.
2. Settings live in `deploy/mac/mac.env` (git-ignored; created from `mac.env.example`): every-page visual
   check, formula OCR, local model, optional PostgreSQL. Restart: `launchctl kickstart -k gui/$UID/com.fidelity.app`.
   Logs: `data/logs/app.*.log`.
3. The installer benchmarks every installed OCR engine and records the best two in `data/ocr_engines.json`
   (re-run any time: `python scripts/ocr_benchmark.py --synthetic --out <dir> --select`; or force with
   `FIDELITY_OCR_ENGINES=applevision,paddle`). Throughput: `PERF_PDF=<pdf> ./deploy/mac/install.sh` or
   `python scripts/perf_benchmark.py --pdf <pdf> --label "Mac mini" --out ../docs/benchmarks/perf-mac`.

**Correction model.** With `FIDELITY_LLM_URL` set, words the two OCR engines still read differently are
put to the local model, which may only choose one of the engines' readings (or a glossary word); numbers
are never decided by the model. Every choice is in the page's correction log.

**Formulas.** `python scripts/formulas.py list <pdf>` lists unreadable formulas (page and order);
`read <pdf>` runs the formula OCR and shows candidates (two engines agreeing are marked `agreed`);
after checking against the source page, `approve <pdf> --page N --k K --latex "…" --reviewer <name>`.
The next distillation publishes it as a reviewed transcription. Nothing is published without approval.

## Server database (PostgreSQL)
SQLite files under `data/` are the default. On a server, point both databases at PostgreSQL 16:
```
FIDELITY_DB_URL=postgresql+asyncpg://fidelity:<password>@<host>:5432/fidelity      # users, audit log
FIDELITY_TRUST_URL=postgresql://fidelity:<password>@<host>:5432/fidelity           # jobs, review decisions
```
The schema is created on first start (Alembic for users/audit; the job tables are created if missing).
`FIDELITY_DB_POOL=1` turns connection pooling on for a busy server. CI runs the whole test suite on
PostgreSQL on every change (`backend-tests-postgres`). To run it yourself, use a database whose name ends
in `_test` — the tests empty it first and refuse any other name.

## Backups
Back up `data/fidelity.db` (users, audit log), `data/trust.db` (jobs) and `data/dropbox_auth.json`
(keep it private). Published Markdown can always be regenerated from the source.

## Troubleshooting
| Symptom | Cause / fix |
|---|---|
| `missing_scope` from Dropbox | re-authorise the role (see Dropbox access) |
| Tesseract not found | install it, or put `tesseract.exe` on PATH |
| A scan always goes to review | expected when engines disagree; check the report's `disagreements` |
| File not found for a long path (Windows) | use the provided commands — they handle long paths |
| GitHub API "rate limit" | wait an hour; do not poll faster than once a minute |


## Deploying an update
`powershell -NoProfile -ExecutionPolicy Bypass -File deploy\windows\deploy.ps1`. Add `-Check` first to see what would change.

The script:
1. Stops if the checkout is not on `main` or has local changes.
2. Makes a backup and checks it.
3. Updates the code to `origin/main`.
4. Installs Python and web packages, but only if their lists changed.
5. Builds the web app into a new folder and swaps it in.
6. Restarts the server process; a distilling run in progress is taken back over.
7. Waits for `/healthz` and the new web bundle.

If the server is not healthy within 7 minutes, the script puts back the previous commit and the previous web app, then restarts. Each step is logged in `data/work/deploy.log`.

## Backups
A verified backup is made each day into `data/backups`, and the newest 14 are kept. Settings → System health shows the last one and has **Back up now**.

To get files back:
1. Stop the scheduled task.
2. Unpack the zip into an empty folder: `python -c "from app.ops import backup as B; B.restore_to(r'<zip>', r'<empty folder>')"` from `backend`.
3. Copy `databases\*.db` to `backend\data`, `backend-data\…` to `backend\data\…` and `data\…` to `data\…`.
4. Start the task again.

Set `FIDELITY_BACKUP_COPY_DIR` to keep a second copy on another disk.
