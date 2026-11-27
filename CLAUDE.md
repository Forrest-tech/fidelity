# CLAUDE.md — how to work on Fidelity

Claude Code reads this file at the start of every session in this repository. It holds the owner's standing rules,
what the system is for, how it runs, and what is still open. Keep it current: when the owner gives a new standing
rule or the state changes, update this file in the same PR.

## 1. What Fidelity is

Fidelity turns the company's source documents (Australian/NZ standards, NCC, drawings, mostly English PDFs, also
scans, Office files and e-mails) into Markdown that AI chat tools (Grok first; Claude, Codex, Gemini too) search to
answer technical questions with **exact clause and page citations**. The distilled files are the company's trusted
knowledge base, so every file is verified (target ≥ 99 % accuracy) before it is published.

- Input: Dropbox folders or shared links (also someone else's shared link). Output: the company library
  `/Library_Installation/Md_Library` in Dropbox. Output files follow the library conventions (front matter,
  `<!-- unit: p0002 | src: p.2 | … -->` page markers, large documents split into chapter files whose names start
  with the document name). No helper files in the output.
- The web app is the back-office: distilling rooms (input → output, queue, live progress), accept/publish with an
  accuracy threshold, page-by-page **Compare & review** (`/review`), correction rules, AI assistance, users with
  roles (viewer / reviewer / admin), sign-up with approval, e-mail, backups, system health. Chinese and English UI.
- The everyday consumer is the Grok skill built from `adapters/` (see `docs/acceptance/`).

Read first: `docs/REQUIREMENTS_V3.md` (current requirements and their status), `docs/PROMPT_V3.md` (how the owner
wants requirements worked out), `docs/PRODUCT_SPEC.md`, `CONVENTIONS.md`, `docs/runbook/`.

## 2. The owner's standing rules (do not ask again)

1. **Decide yourself, report the final result.** Do not stop to ask questions mid-work. Score the options, pick the
   best, finish it, then report once: what changed, measured evidence, what is still open. Only hand back what is
   truly the owner's: payments, administrator rights on their machines, settings in external consoles (Dropbox
   App Console, GitGuardian, Google), and anything a safety rule reserves for a person.
2. **Test before saying "done", like a software tester, with real data.** Every function, boundary values, invalid
   input, error paths, and a real end-to-end run on a live-like but isolated setup (the owner's real Dropbox links,
   a separate data folder). Not only unit tests with fakes. Check the UI in a browser (desktop and phone width,
   light and dark). The owner must never be the one who finds the bugs.
3. **Deeper, not bigger.** Before any requirement or change: (1) redefine the problem and its hidden assumptions;
   (2) start from raw records (source PDFs, logs, job tables) with numbers; (3) score every option, improve anything
   under 9.5/10; (4) two independent proofs for each key conclusion; (5) proof beyond the owner and Claude; (6) then
   rewrite the requirement and do it. Prefer finishing and stabilising over adding scope. Find the **root cause**.
4. **Delivery:** work on a branch, open a PR, merge it yourself once all CI checks are green (no approval needed).
   Never push to `main` directly, never force-push.
5. **Iron rule — the source is read-only.** Never add, change or delete anything in an input folder (e.g. Dropbox
   `/2025`, `/AS 3500`, anyone's shared link). Writes go only to the chosen output folder. The code enforces this
   (read-only Dropbox role for input, output must lie outside the input); keep it that way.
6. **No secrets in the repository.** No keys, tokens, passwords or real link keys in code, tests or docs; tests make
   their own values (see `web/playwright.config.ts`). gitleaks runs in CI on every commit of a PR. Never send the
   owner's e-mail address or personal data to outside services.
7. **Licences:** the company is licensed for this content. Copy-restricted PDFs are read (text layer, checked against
   page images; scans by OCR). Licence stamps are recorded, never block publishing. Do not break real DRM.
8. Free / open-source components only; use the best-rated existing component for each job rather than writing one.
9. Reply to the owner in Chinese; code, commits and docs in English.

## 3. Where it runs

- **Production: the owner's Mac (Docker).** One click: `deploy/mac/Fidelity-Docker-启动.command` (pulls `main`,
  builds for the Mac's own chip, starts the container, opens http://127.0.0.1:8000). Stop:
  `Fidelity-Docker-停止.command`. Data lives in the Docker volumes `fidelity-data` and `fidelity-appdata`; daily
  backups are also copied to `~/FidelityBackups`. After a merge the owner double-clicks the start script to update.
- **Development:** on the Mac mini (from 2026-11-27). Run the app natively for development and tests
  (`deploy/mac/install.sh`, `deploy/mac/run.sh`, or backend `uvicorn` + `npm run dev`), keep the Docker instance for
  real use. Use a separate data folder for test servers: `FIDELITY_DATA_DIR=<folder>` gives a server (and the runs
  it starts) its own settings, users, rooms and work files, i.e. a brand-new installation.
- The old Windows VM is no longer a deployment target (`deploy/windows/` is kept for reference).

## 4. Code map

- `backend/app/` — FastAPI. `distill/` the pipeline (triage → text-layer extraction or OCR → structure → verify →
  publish; `sync.py` is the run, `scan.py`/`ocr.py` OCR, `verify.py` the checks, `scoring.py` accuracy),
  `jobs/` queue, capacity, rooms (`rooms.py`), page compare (`page_review.py`), `api/` routes, `auth/`, `ai/`.
- `web/src/` — React + antd. `pages/DistillPage.tsx` (rooms), `pages/ReviewPage.tsx` (compare & review),
  `components/RoomFiles.tsx`, `FixDrawer.tsx`, locales in `locales/zh.json` / `en.json` (every visible text in both).
- Tests: `backend/tests` (pytest; SQLite and PostgreSQL in CI), `web/src/test` (vitest), `web/e2e` (Playwright,
  accessibility and phone/tablet/desktop). CI also builds the Docker image and distils text, copy-restricted and
  scanned PDFs inside it as a new installation (`backend/scripts/docker_distill_e2e.py`).

## 5. Things learned the hard way

- Test as a **new installation**: a setting that exists only on the developer's machine hid a bug that failed every
  file on the Mac (2026-11-26). Default values in code must be the owner's decisions.
- In Docker read memory as `MemAvailable` and respect cgroup limits (`jobs/capacity.py`); "free" memory made the Mac
  read one file at a time.
- An x86 image on Apple silicon is several times slower; the start script builds natively and the page warns.
- Runs must carry on, not start again: finished files are skipped, downloads resume (HTTP Range), OCR pages are kept
  per page (`<cache>/ocr-pages/<hash>.jsonl`).
- SQL must work on SQLite and PostgreSQL (no `IS` between columns, no two-argument `MAX`).
- A value that looks like a key in a test (even a Dropbox `rlkey`) fails gitleaks; use dummy values.

## 6. Open items (2026-11-27)

- Verify on the owner's Mac after updating: OCR speed per page, several files read at once, the emulation warning.
- One-click Dropbox connect needs the redirect URIs added in the Dropbox App Console by the owner:
  `http://127.0.0.1:8000/api/v1/storage/dropbox/callback` and `http://localhost:8000/api/v1/storage/dropbox/callback`.
- A few server error messages are still English only.
- GitGuardian: an old commit holds the former fixed e2e test password (a throw-away test database); the owner closes
  the incident as a test credential.
- Remaining P1/P2 items: see `docs/REQUIREMENTS_V3.md`.
