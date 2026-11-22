# Fidelity — Product Specification

| | |
|---|---|
| Status | Draft for owner review |
| Version | 1.0 (2026-11-17) |
| Owner | Forrest Lin |
| Rule | This document is the source of truth. A change of requirement is made here first, then in code. |
| Superseded in part | Requirements v2 (`REQUIREMENTS_V2.md`, accepted 2026-11-22) replaces sections 3, 9 and 11; where they differ, v2 wins. |

## 1. Purpose

Fidelity turns a company's source documents (standards, codes, technical documents, emails,
drawings, web snapshots) into **verified, citable Markdown** stored in a cloud folder. Staff ask
questions in an AI chat tool (Grok today; Claude, Codex and Gemini later). The AI reads the Markdown
through a storage connector and answers with the exact clause, page and source.

Because the Markdown is used as trusted knowledge, the product's core job is not conversion but
**assurance**: nothing is published as trusted unless it has been checked against its source.

Out of scope: the AI chat tools themselves, and answering questions inside Fidelity.

## 2. Terms

| Term | Meaning |
|---|---|
| Source | An original file in the source folder. Never modified. |
| Distill | Convert a source into Markdown plus provenance. |
| Knowledge base (KB) | The published Markdown tree, e.g. `/Library_Installation/Md_Library`. |
| Unit | One source page (or slide, sheet, email part) inside a Markdown file. |
| Verification gate | The automatic checks a document must pass before publication. |
| Trusted tier | Content whose status is auto-verified or human-verified. |
| Adapter pack | Instructions for one AI tool (for Grok: the `au-compliance-kb` skill). Lives outside the KB. |

## 3. Requirements

Each requirement has an ID. Section 13 maps every ID to the phase that delivers it.

### 3.1 Iron rules (never traded off)

| ID | Rule |
|---|---|
| IR-1 | **The source folder is read-only.** No create, modify, move or delete, ever. Enforced by read-only credentials, a write allow-list, and before/after snapshots. |
| IR-2 | **Only verified content is published as trusted.** A document that fails verification is not published. |
| IR-3 | **No bypass of copy protection.** DRM-protected files are not decrypted or circumvented. |
| IR-4 | **Never fabricate.** Content that cannot be read reliably is flagged, not guessed. |

### 3.2 Functional requirements

| ID | Requirement |
|---|---|
| F-1 | Input by Dropbox folder link or path. Further connectors: Google Drive, local folder. Upload from the browser for files not in cloud storage. |
| F-2 | Output destination is selectable (Dropbox, Google Drive, local). The output mirrors the source folder structure, including the source folder's own name (source `/2025/...` → output `<destination>/2025/...`). |
| F-3 | Formats: PDF with text layer; scanned PDF and images (jpg, png, tif); Word, Excel, PowerPoint; Outlook `.msg` with attachments processed recursively; web snapshots (html, md); drawings; zip. New formats are added as plug-ins. An unsupported file is listed, never silently skipped. |
| F-4 | English first. Other languages are detected, tagged in the output, and processed at lower priority. |
| F-5 | Provenance in every file: physical page number (and printed page label where it differs), clause IDs, source path and content hash. |
| F-6 | **Zero auxiliary files in the KB.** No README, catalog, index or report files. Folder and file names are the index. Audit data stays in Fidelity. |
| F-7 | Hybrid output. A small document is one Markdown file. A large document becomes a folder of chapter files split along the document's own structure; a clause or table is never split. Chapter file names start with the document name (storage search matches file names only). |
| F-8 | Output is compatible with the existing `Md_Library` conventions (front-matter keys and unit markers) so the existing Grok skill keeps working. |
| F-9 | Metadata per document: standard id, year and kind; jurisdiction; edition status (draft, published, superseded); source URL and retrieval date for web content; audit status. Extracted automatically, confirmed by a person where uncertain. |
| F-10 | Drafts are marked "not in force" in every file. |
| F-11 | Each chapter file lists clauses it cites that live in other files, with their location. |
| F-12 | Drawings are distilled: title block (number, title, revision, date, scale, project), text annotations, a reference to the source page, and a notice that spatial relationships must be read from the original. |
| F-13 | Protected files are detected and listed as "protected, not distilled". A metadata-only entry may be published. Content exported by the licence holder may be uploaded with a recorded licence attestation. |
| F-14 | Automatic correction for OCR output, in layers: targeted re-OCR; rule-based fixes (confusable characters in numeric context, units, hyphenation, ligatures); a glossary learned from verified documents; a constrained local model on the Mac (may only edit flagged spans, only to a value seen by an engine or in the glossary); human corrections fed back into the rules. Every change is logged and reversible. |
| F-15 | Verification gate with three outcomes: pass (publish), review (human queue), fail (not published). Checks are listed in section 6.4. |
| F-16 | Review workflow: side-by-side source and Markdown with highlights; a risk-ordered queue; sampling of auto-passed documents; every decision recorded with reviewer and time. |
| F-17 | Incremental and resumable processing. Unchanged sources are skipped. Scheduled sync. When a source is updated it is re-distilled; renames and deletions wait for administrator confirmation before published files are touched. |
| F-18 | Publishing goes to a staging area first, is validated, then promoted as a whole; the previous version is kept for rollback. The KB folder is read-only for staff; only the Fidelity system account writes to it. Published files are checked periodically against recorded hashes; any outside change raises an alert. |
| F-19 | Adapter packs: the Grok skill (primary) and equivalents for Claude, Codex and Gemini, generated from one template and from KB metadata so that facts such as "latest edition held" do not go stale. |
| F-20 | Web application, redesigned: left navigation and separate pages (Overview, Sources, Jobs, Documents, Review, Settings, Users); empty, loading and error states on every page; responsive layout; Chinese and English. |
| F-21 | Login with username and password; roles administrator, reviewer, viewer; an interface reserved for single sign-on; an audit log of user actions. |
| F-22 | Triage before distilling: text document, scan, drawing, photo, protected, unsupported. Each class has its own route. |
| F-23 | Scan distilled text for instruction-like content aimed at an AI ("ignore previous instructions") and flag it; adapter packs state that KB content is data, not instructions. |
| F-24 | Each source can be mapped to its own output folder so confidential sources (for example email) are published where fewer people have access. Access control itself stays with the storage provider's folder permissions. |
| F-25 | Staff can report a wrong answer. A confirmed error is fixed and added to the regression set. |
| F-26 | Duplicate sources are detected by content hash. |

### 3.3 Quality requirements

| ID | Requirement |
|---|---|
| Q-1 | Recognition accuracy for the trusted tier: character accuracy at least 99%; numbers 100%. Measured against source, not vendor claims. |
| Q-2 | Answer accuracy: at least 99% of questions correct on an agreed question bank, judged per question. Trap questions (unreadable, missing, draft) must never produce an invented answer. Questions use standard industry English and include hard categories (no clause number given, cross-chapter, state variations, draft versus published, false premises). The test plan is agreed after the system is built. |
| Q-3 | Low token use and fast retrieval: a chapter file targets about 10,000–30,000 tokens; an AI needs at most a few listings and one file read to answer. |
| Q-4 | Free to run: open-source software and free APIs only; no paid model API. |
| Q-5 | Open-source first: every module uses the best-established open-source component rather than new code, unless none fits. |
| Q-6 | Maintainable and extensible: core rules independent of external components; plug-ins for formats, engines, storage and AI tools. |
| Q-7 | Stable and reproducible: stages are idempotent; the same source and pipeline version give the same output; interrupted runs resume. |
| Q-8 | Scale: a corpus of about 7.8 GB; target hardware Mac mini (M6, 32 GB memory, 512 GB disk), development on a 4 GB CPU-only VM; about 30 staff, most of whom only use the AI tool; a few administrators and reviewers use Fidelity. |
| Q-9 | Portable: runs on the Mac mini first (office network), later on a dedicated server (Linux); SQLite first, PostgreSQL later, without changing business code. |
| Q-10 | Security baseline (section 8). |
| Q-11 | Output is tool-agnostic plain Markdown; no feature depends on one AI vendor. |
| Q-12 | Modern, consistent interface built on a design system; accessible (contrast, keyboard, labels); light and dark themes. |

### 3.4 Process requirements

| ID | Requirement |
|---|---|
| P-1 | All work on branches with pull requests. A PR merges only when all automated checks pass. |
| P-2 | A full test framework is part of the product (section 9). |
| P-3 | Each phase has a written definition of done; the system is handed over only after verification passes. |
| P-4 | The existing 1,721 Markdown files and the source corpus are left untouched until the system is complete; then everything is re-distilled from source. |
| P-5 | A licence inventory of all dependencies is produced in CI. (PyMuPDF is AGPL; accepted for internal use by the owner on 2026-11-17; revisit before any external use.) |
| P-6 | Documentation: user manual and administrator runbook in Chinese and English; architecture decision records; a repository conventions file for future developers and AI sessions. |
| P-7 | Staff are told before cutover what changes and how to update the skill. |
| P-8 | This specification is kept current (see Rule in the header). |

## 4. Decision log

| Date | Decision | Reason |
|---|---|---|
| 2026-11-16 | Layered pipeline with cross-checking and a publish gate, not a single OCR model | No single engine guarantees 99%; agreement between independent readers is the evidence |
| 2026-11-16 | Split large documents by chapter | A whole standard exceeds what an AI reads in one call; splitting cuts tokens by about 90% per query |
| 2026-11-16 | Zero auxiliary files; audit kept locally | Owner requirement; the adapter pack carries usage rules instead |
| 2026-11-17 | Hybrid: small documents stay single-file | 92% of existing files are under 50 KB; only 61 files (3.5%) are over 150 KB yet hold 69% of bytes |
| 2026-11-17 | Chapter file names start with the document name | Measured: Dropbox search matches file names, not Markdown body text, and does not return folders by default |
| 2026-11-17 | Keep existing front-matter keys and unit markers | The live Grok skill depends on them |
| 2026-11-17 | Open-source components for every module; own code only for verification, splitting/naming, read-only guard | Fewer bugs, lower maintenance |
| 2026-11-17 | Username/password login now, SSO interface reserved | Owner decision |
| 2026-11-17 | Mac mini first, dedicated server later | Owner decision; drives Q-9 |
| 2026-11-17 | No DRM bypass; vendor licence, metadata-only entry, or licensed manual export | Legal and contractual |
| 2026-11-17 | Drawings are distilled with references and a notice | Owner decision |
| 2026-11-17 | The 300-question acceptance run is deferred until the system is built | Owner decision |
| 2026-11-17 | Analysis and decisions with the most capable model; development with a cheaper model | Owner preference |

## 5. Current state (2026-11-17)

**Existing application** (FastAPI + React, running locally): reviews an existing Markdown against its
source side by side. Assessed at 52/100 as a company product: no login (29 open API routes), one
811-line routes file, one 809-line UI component with no page routing, a single crowded screen that
breaks at narrow widths, hand-written SQL without migrations. Assets worth keeping: the side-by-side
comparison with highlights, 151 passing unit tests, the job queue, bilingual strings.

**Distillation pipeline** (`backend/app/distill/`, command line, not yet committed): text-layer PDFs
only. Five NCC 2025 PDFs (2,528 pages) pass verification — pages 100%, headings 100%, characters
99.99%, numbers 100%, agreement with a second extractor 100% — and are published to a test folder
with zero auxiliary files. About 490 formula lines are unreadable in the source text layer and are
flagged. Source folder verified unchanged after every run.

**Grok test** (20 questions through the Dropbox connector): 18 correct, 1 partly correct (a state
variation described as "adds" instead of "replaces"), 1 failed (inferred an unreadable formula). All
17 factual look-ups were correct with correct clause and page. Simple look-ups took 6–18 s;
text-search questions 36–74 s. Listing a folder costs about 330 tokens per entry.

**Known gaps in the test output**: chapter file names lack the document-name prefix; page markers
use `[p.N]` instead of the library's unit markers; a watermark leaves stray letters in one draft.
All are fixed in Phase 2.

## 6. Architecture

### 6.1 Layers

```
Storage adapters (read-only source / guarded sink)   Dropbox · Google Drive · local
Job orchestration                                    states in DB, resumable, incremental, scheduled
Triage                                               text · scan · drawing · photo · protected · unsupported
Extraction adapters (plug-ins)                       PDF text layer · Office/HTML · email · OCR engines
Document model (core)                                pages → blocks with page, bbox, engine, confidence
Structure & splitting (core)                         headings, clauses, hybrid single-file / chapter folder
Correction (core + adapters)                         rules, glossary, constrained model, human feedback
Verification gate (core)                             pass · review · fail
Publishing (core + storage adapter)                  staging → promote → rollback, integrity monitor
Adapter packs                                        Grok skill · Claude · Codex · Gemini
Web application & API                                auth, roles, review, administration
```

The core (document model, structure, verification, publishing policy) has no direct dependency on
any external component. Everything else is an adapter behind an interface.

### 6.2 Pipeline

Stages: discover → download → triage → extract → structure → correct → verify → stage → publish.
Each stage's result is cached under (source content hash, stage version). Consequences: an
interrupted run resumes; changing only the splitting rules does not re-extract; identical input and
versions give identical output. Source files are processed one at a time: each document is
distilled, verified and published before the next starts, and its local copy is removed afterwards,
so the whole corpus never has to be held on local disk.

### 6.3 Trust tiers

`audit_status` in each file: `auto_verified`, `human_verified`, `pending_review`. Per-unit `flags`
mark low confidence, unreadable regions and instruction-like text. Q-1 and Q-2 apply to the first
two tiers.

### 6.4 Verification gate

| Check | Catches | Requirement |
|---|---|---|
| Page completeness | Missing or repeated pages | 100% |
| Heading completeness | Lost sections or clauses | 100% of bookmarks/detected headings |
| Character recall and precision per page | Dropped or duplicated text | at least 99.5% recall; no unexplained extra text |
| Number fidelity per page | Wrong or missing numbers | 100% |
| Second-extractor agreement | Broken font encoding | at least 99% |
| Table cell check (new) | Values in the wrong column | every cell maps to its source position |
| Visual cross-check (new) | A wrong text layer: render page, OCR, compare | sampled on the VM, every page on the Mac |
| OCR agreement and confidence | Recognition errors | engines agree; disagreements go to review |
| Source unchanged | Any change to a source during the run | identical id, revision and hash |

### 6.5 Output format

**Hybrid rule.** Up to a size threshold (initially about 100 KB of Markdown, tuned by measurement) a
source `X.pdf` becomes `X.pdf.md` at the mirrored path, exactly as today. Above it, the source
becomes a folder at the mirrored path containing chapter files.

**Chapter file name.** `<document name> · <NN> <chapter title> [<first>–<last clause>] p<from>-<to>.md`,
with a fixed length cap. Glossary-type chapters are named by letter range.

**Front matter.** Existing keys are kept (`source_filename`, `source_relative_path`,
`source_file_hash`, `std_id`, `std_year`, `std_kind`, `parser`, `units`, `audit_status`, `flags`, …).
Added: `format_version`, `edition_status`, `jurisdiction`, `source_url`, `retrieved_date`, `languages`,
`chapter`, `pages`, `clauses`.

**Unit marker.** `<!-- unit: p0002 | src: p.2 | chars: 1460 | flags: - -->` … `<!-- /unit -->`, as in the
existing library. Clause headings also carry the page.

**Content rules.** Text is copied, never paraphrased. Defined terms keep their emphasis. Tables are
Markdown tables with repeated headers. Explanatory (non-mandatory) content is marked. Unreadable
formulas are replaced by a marker that tells the reader not to infer and to open the source page.
A state variation heading states the state and whether it replaces or adds to the national clause.

### 6.6 Adapter packs

One template, rendered per tool. Contents: scope of access, search-then-answer rule, how to navigate
single files and chapter folders, how to read unit markers, citation format, trust-tier and draft
rules, the three rules learned from testing (do not infer unreadable formulas; a variation
"replaces" unless it says "adds"; drafts are not in force), and library facts generated from
metadata. Kept in the repository and in the tool's own skill store — not in the KB.

Goal: staff need no extra instructions after cutover. One known exception: the current skill lists a
few hard-coded file paths (for example the AS/NZS 3500.2 file); those documents become chapter
folders, so these lines are updated once when the pack is regenerated.

## 7. Technology choices

| Module | Component | Note |
|---|---|---|
| Text-layer PDF | PyMuPDF (existing pipeline) | Already verified at 99.99% |
| Office, HTML, images, OCR framework, document model | Docling | To be confirmed by Spike 1 |
| Email | extract-msg | Then routed through the same extractors |
| OCR engines (VM) | RapidOCR, Tesseract 5 | CPU baseline |
| OCR engines (Mac) | MLX builds of current document models | Chosen by benchmark on arrival |
| Storage | rclone | Dropbox, Google Drive, OneDrive, local |
| API | FastAPI, versioned `/api/v1` | TypeScript client generated from OpenAPI |
| Auth | FastAPI Users (or the maintained equivalent) | Spike 2 |
| Database | SQLAlchemy + Alembic; SQLite then PostgreSQL | |
| Jobs | Huey with SQLite storage | No extra server |
| UI | React, Vite, shadcn/ui, Tailwind, TanStack Query, React Router, react-i18next, PDF.js | |
| Config and logs | pydantic-settings, structlog | |
| Quality tools | pytest, Vitest, Playwright, Storybook, axe-core, Lighthouse, ruff, type checking, GitHub Actions | |

**Spikes before committing** (short experiments, results recorded as decision records):
1. Docling versus the current extractor on the NCC set, scored by our verifier; can it run on the 4 GB VM?
2. Maintenance status of the auth library; choose the maintained option.
3. rclone with a read-only credential for the source.

## 8. Security

Login rate limiting and session expiry; HTTPS on the office network; CORS limited to the
application's own origin; every API route requires authentication by default; role checks on every
mutating route; uploaded files parsed in an isolated subprocess with size and time limits; storage
credentials in the operating system keychain, never in the repository; dependency vulnerability
scanning and secret scanning in CI; audit log of user actions; database backups.

## 9. Testing

| Layer | Scope | Tool | Runs |
|---|---|---|---|
| Unit | Rules: splitting, naming, verification, guards | pytest | every commit |
| API | Every route, including auth and roles | pytest | every commit |
| Front-end unit | Component behaviour, language switch | Vitest | every commit |
| End-to-end | Real browser: login → add source → distill → review → publish | Playwright | every PR |
| Accuracy regression | Golden documents re-distilled and compared | pytest | sample per PR, full set nightly and on dependency upgrades |
| Components | Each component in every state | Storybook | every PR |
| Visual regression | Screenshot comparison (baselines made in CI on Linux) | Playwright | every PR |
| Accessibility | Contrast, keyboard, labels | axe-core | every PR |
| Responsive and bilingual | Phone, tablet, desktop × Chinese, English | Playwright | every PR |
| Performance and practice | Load and common front-end issues | Lighthouse | every PR |
| Iron rules | Write guard paths; read-only credential cannot write; source snapshot unchanged | pytest | every PR |
| Human trial | Two or three staff follow task scripts | manual | before handover |

Golden set: the five NCC documents; a varied set of public documents (notices, manuals,
table-heavy documents, drawings); synthetic scans made by rendering text-layer pages to images with
skew, blur and noise, which gives exact ground truth for OCR accuracy.

Rules: PRs merge only when all checks pass (branch protection). The existing 151 tests are migrated,
not dropped. Coverage target for the three core modules is 90% or more.

## 10. Operations

Mac mini: native install (local models need the GPU, which containers on macOS cannot use),
dependencies locked, service starts with the system. Server later: Linux service or containers; the
application is unchanged. Staging and production instances. Monitoring page (volume, pass rate,
queue, failures), error collection, email on serious errors. Database and audit backups. Cache and
disk policy: local source copies are deleted after processing; caches expire by age.

## 11. Roadmap and definitions of done

| Phase | Scope | Done when |
|---|---|---|
| 0 Specification | This document | Approved by the owner |
| 1 Foundation | Branch/PR flow and branch protection; CI; migrate tests to pytest; split and version the API; database layer and migrations; auth and roles; security baseline; licence inventory; conventions file; the three spikes | All checks green; 151 migrated tests pass; unauthenticated requests are refused; spike results recorded |
| 2 Distillation as a product | Pipeline stages with cache; job integration; hybrid output in the library's conventions; metadata; fixes from the Grok test; table cell check; incremental sync and batch upload; staging/promote/rollback; triage; protected-file detection; duplicate detection | Five NCC documents pass in the new format; a re-run skips unchanged files; a planted table error is caught; iron-rule tests pass |
| 3 Interface | New navigation and pages; review screen carried over and improved; design system; bilingual; all UI test layers | End-to-end, visual, accessibility and responsive checks pass; every page has empty, loading and error states |
| 4 Formats and OCR framework | Office, email, web snapshots; images and scans with two CPU engines, voting and review routing; correction layers that do not need the Mac; drawings; visual cross-check by sampling; instruction-text scan; synthetic-scan benchmark | Each format has samples and tests; low-confidence content reaches the review queue; OCR accuracy is reported on the synthetic set |
| 5 Adapter packs and handover | Updated Grok skill; packs for other tools; manuals and runbook; acceptance test plan agreed with the owner; human trial | Owner accepts against this specification |
| 6 Mac mini | Install; high-accuracy engines chosen by benchmark; visual cross-check on every page; formulas and figures; constrained correction model; performance measured | Scans reach Q-1 on the synthetic set; throughput measured on real hardware |
| 7 Re-distillation | Pilot folder, then staged roll-out of the whole corpus into `Md_Library`; staff communication | Pilot verified with the AI tool; each roll-out step can be rolled back |
| 8 Server | Move to a dedicated server; PostgreSQL | Same test suite passes on the server |

## 12. Known limits and assumptions to validate

**Limits.** Handwriting and very poor scans cannot reach 99% and go to human review. Requirements
shown only in figures are captured in part. The behaviour of each AI tool's storage connector is
outside our control. Protected files without a suitable licence are metadata-only.

**Assumptions not yet validated.**
1. The pipeline generalises beyond NCC-style documents (first evidence: Phase 2/4 public test set; proof: Phase 7 pilot).
2. OCR on the Mac reaches Q-1 at acceptable speed (Phase 6 benchmark).
3. Docling is accurate enough and runs on the VM (Spike 1).
4. The size threshold and chapter size give the best token cost (measured in Phase 5 acceptance).
5. Most technical documents without bookmarks can be split by detected headings (Phase 4).

## 13. Requirement traceability

| Requirement | Phase | | Requirement | Phase |
|---|---|---|---|---|
| IR-1 | done; hardened 1–2 | | F-21 | 1 |
| IR-2 | done; extended 2, 4 | | F-22 | 2 |
| IR-3 | 2 | | F-23 | 4 |
| IR-4 | done; extended 2, 4 | | F-24 | 2 |
| F-1 | Dropbox done; others 2–4 | | F-25 | 5 |
| F-2 | Dropbox done; others 2–4 | | F-26 | 2 |
| F-3 | PDF done; 4 | | Q-1 | text PDF done; scans 6 |
| F-4 | 4 | | Q-2 | 5 (plan), 7 (proof) |
| F-5 | done; format aligned 2 | | Q-3 | 2, measured 5 |
| F-6 | done | | Q-4 | all |
| F-7 | 2 | | Q-5 | 1 onward |
| F-8 | 2 | | Q-6 | 1–2 |
| F-9 | 2 | | Q-7 | 2 |
| F-10 | done | | Q-8 | 2, 6, 7 |
| F-11 | done | | Q-9 | 1, 8 |
| F-12 | 4 | | Q-10 | 1 |
| F-13 | 2 | | Q-11 | 2, 5 |
| F-14 | 4, 6 | | Q-12 | 3 |
| F-15 | done; extended 2, 4, 6 | | P-1 | 1 |
| F-16 | 3 | | P-2 | 1–4 |
| F-17 | 2 | | P-3 | every phase |
| F-18 | 2 | | P-4 | 7 |
| F-19 | 5 | | P-5 | 1 |
| F-20 | 3 | | P-6 | 1, 5 |
| | | | P-7 | 7 |
| | | | P-8 | every phase |

## 14. Open questions

1. Vendor and licence terms of the protected standards (owner to check with the licence holder).
2. Acceptance test plan and question bank (to be agreed in Phase 5; real staff questions preferred once chat logs exist).
3. Whether external (out-of-office) access is needed after the move to a server.
