# ADR 0004 — Phases 6–8: what is done on the VM, what waits for hardware or sources

Date: 2026-11-18. Status: accepted (owner asked to complete all development and testing without
further confirmation).

## Phase 8 — server database: done
- Users/audit (SQLAlchemy) and the job/review tables (formerly raw `sqlite3`) both run on
  PostgreSQL 16, selected by `FIDELITY_DB_URL` / `FIDELITY_TRUST_URL`; SQLite stays the default.
  The job tables go through a small adapter in `app/db.py` (sqlite-style `?` SQL → psycopg).
- **The same test suite passes on PostgreSQL** (417 tests locally; CI job `backend-tests-postgres`
  on every change). Tests refuse to run against a database not named `*_test`.
- Moving to a dedicated machine is configuration only (runbook, "Server database").

## Phase 6 — Mac mini: development complete; measurement on the machine itself pending
Built (2026-11-18, tested here and on macOS in CI):
- **Engines chosen by benchmark**: OCR engines are plug-ins — Apple Vision (`ocrmac`, macOS), PaddleOCR 3
  (PP-OCRv5), RapidOCR (English model), Tesseract 5. `ocr_benchmark.py --select` ranks every installed
  engine and records the best two (`data/ocr_engines.json`); the first one's text is published.
- **Visual cross-check on every page**: `FIDELITY_VISUAL_SAMPLES=all` (Mac profile).
- **Formulas**: unreadable formulas are located, cropped and read by formula OCR (pix2tex); candidates
  go to a reviewer (`scripts/formulas.py`); only an approved transcription replaces the marker, labelled
  as reviewed. **Figures**: pages with a large image get a "figure not reproduced, see the page" notice.
- **Constrained correction model**: local model (Ollama) chooses only between the engines' readings (or a
  glossary word) where they disagree; numbers never; every choice logged; off unless configured.
- **Install**: `deploy/mac/install.sh` (Homebrew, venv with locked versions, models, web build,
  launchd service that starts at login and restarts), `mac.env` profile.
- **Performance measured**: `scripts/perf_benchmark.py`; VM baseline 43.6 pages/min (text), OCR
  Tesseract 4.8 s/page, RapidOCR 53 s/page; the macOS CI job records the same on Apple silicon.

Still to do on the Mac mini itself (needs the hardware, not code): run `install.sh`, record
`docs/benchmarks/ocr-mac.md` and `perf-mac.md`, and confirm "scans reach Q-1 on the synthetic set" with
the engines it selects.

## Phase 7 — re-distillation: blocked on the source corpus
`/Library_Installation/Md_Library` (1,732 files) is reachable, but its **source documents are not**
in the connected Dropbox (searches for known titles return only the `.md` files). The pipeline,
staging/promote/rollback and the acceptance bank are ready; the pilot starts as soon as the owner
provides the source folder link. NCC 2025 (the only sources held) is already distilled in the new
format and verified with Grok (`docs/acceptance/`), which serves as the pilot evidence so far.
