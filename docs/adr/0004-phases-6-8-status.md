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

## Phase 6 — Mac mini: VM-feasible parts done; the rest waits for the machine
Done here:
- Visual cross-check on **every page** (`FIDELITY_VISUAL_SAMPLES=all`); default stays 3 samples on
  the VM because OCR is slow here.
- Throughput measured (`scripts/perf_benchmark.py`, `docs/benchmarks/perf-vm.md`): text PDFs
  43.6 pages/min; OCR Tesseract 4.8 s/page, RapidOCR 53 s/page. Re-run the same script on the Mac.
- OCR engines chosen by benchmark on the VM (`docs/benchmarks/ocr-vm-*.md`): RapidOCR English model
  with the angle classifier off + Tesseract 5, voting, glossary.

Waiting for the Mac mini (needs its GPU / memory; not attempted on a 4 GB VM):
- higher-accuracy engines benchmarked on real hardware ("scans reach Q-1 on the synthetic set");
- formula and figure recovery (the ~490 unreadable formulas stay marked "check the source page");
- the constrained local correction model.

## Phase 7 — re-distillation: blocked on the source corpus
`/Library_Installation/Md_Library` (1,732 files) is reachable, but its **source documents are not**
in the connected Dropbox (searches for known titles return only the `.md` files). The pipeline,
staging/promote/rollback and the acceptance bank are ready; the pilot starts as soon as the owner
provides the source folder link. NCC 2025 (the only sources held) is already distilled in the new
format and verified with Grok (`docs/acceptance/`), which serves as the pilot evidence so far.
