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
- Create or reset a user: `python scripts/create_admin.py name@example.com --role admin|reviewer|viewer`
  (password is prompted, or taken from `FIDELITY_NEW_PASSWORD`; never on the command line).
- admin: everything · reviewer: review queue and decisions · viewer: read only.
- Sign-in is limited to 5 attempts per IP per 5 minutes; attempts are in the audit log.

## Dropbox access
Two app roles, both stored in `data/dropbox_auth.json`:
- **reader** (read-only scopes) — used for the source and for read-only copies.
- **writer** — used only for the destination; the guarded writer refuses any path outside it.

Re-authorise (e.g. after a scope change): `python -m app.distill.dropbox_io auth --app-key <key> --role reader --read-only`
(or `--role writer`). Follow the link, paste the code.

## Distil and publish
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
