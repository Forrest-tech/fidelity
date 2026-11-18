# Repository conventions

For developers and AI sessions. The source of truth for requirements is `docs/PRODUCT_SPEC.md`; read it first and keep it current.

## Iron rules
- The Dropbox source folder is read-only. Never write, move or delete there. All writes go through `app.distill.dropbox_io.SafeWriter`; `backend/tests/test_distill_guard.py` must stay green.
- Only verified content is published.
- Never commit anything under `data/` (credentials, work files) or any secret.

## Workflow
- Work on a branch, open a PR, merge only when checks `backend-tests` and `frontend-build` pass (branch protection enforces this). Never push to `main`.
- Commit messages: `type: summary` (feat, fix, test, ci, docs, chore).
- Open-source components first; write our own code only for verification, splitting/naming and the read-only guard.

## Backend (`backend/`, Python 3.11)
- Create the venv at `.venv`; install with `PYTHONUTF8=1 pip install -r backend/requirements.txt pytest`.
- Run tests: `cd backend && python -m pytest -q`. New tests are native pytest in `backend/tests/`. `test_legacy_*.py` adapt the old script suites; do not delete checks.
- Layout: `app/api` routes, `app/domain` core logic, `app/ingest` extractors, `app/distill` pipeline, `app/jobs` queue.
- API is versioned under `/api/v1`.

## Frontend (`web/`, Node 20)
- `npm ci`, `npm run build` (type-check plus build). The UI is redesigned in Phase 3 with Chinese and English (react-i18next); do not add hard-coded user-facing strings to new code.

## Web tests (`web/`)
- `npm test` (Vitest unit tests), `npm run build` (type-check + build).
- `npm run e2e` (Playwright: real backend, desktop/tablet/phone, accessibility, bilingual, visual). Set `PYTHON` to the venv python.
- `npm run build-storybook && npm run check-stories` (every story through axe in light/dark and en/zh).
- Visual baselines are Linux-only: run the "Update visual baselines" workflow on your branch to refresh them.

## Licences
- CI publishes a licence inventory artifact. PyMuPDF is AGPL, accepted for internal use only; revisit before any external use.

## Adapter packs and handover docs (Phase 5)
- One template `adapters/template.md.j2`; owner rules in `adapters/house_rules.yaml`; tools in
  `adapters/tools.yaml`. Generated packs in `adapters/dist/` — never edit them by hand; regenerate with
  `python -m app.adapters.build --library <local library copy>`.
- Library facts in packs (editions, drafts, counts, paths) must come from the library, never be typed.
- Manuals: `docs/manual/user.{en,zh}.md`; runbook: `docs/runbook/admin.{en,zh}.md` — change both
  languages together. Acceptance: `docs/acceptance/`.
