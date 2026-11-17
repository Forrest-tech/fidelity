# ADR 0001: Docling versus the current extractor (Spike 1)

Date: 2026-11-17. Status: accepted (partial evidence; see limits).

**Question.** Can Docling replace PyMuPDF for NCC-style text-layer PDFs, and can it run on the 4 GB VM (spec section 7, assumption 3)?

**Method.** First 5 pages of `NCC 2025 PCD - Volume One.pdf` (read-only source copy; slice and output in a scratch folder), Docling 2.150.1 CPU in an isolated venv, default pipeline (layout + table models). Compared with PyMuPDF text: share of PyMuPDF word tokens that appear in the Docling Markdown.

**Results.**
| Measure | Docling | PyMuPDF (existing) |
|---|---|---|
| Time, 5 pages | 168 s convert + 32 s model load (~34 s/page) | ~0.1 s/page |
| Peak memory | 1.2 GB | small |
| Token recall vs PyMuPDF | 94.1% | reference (99.99% by our verifier) |
| Install size | torch plus models, several GB | ~50 MB |

**Decision.**
- Keep PyMuPDF as the engine for text-layer PDFs; Docling's recall is far below the Q-1 target, and ~34 s/page makes a 600-page volume take hours.
- Docling runs on the 4 GB VM (1.2 GB peak), but only one document at a time and with little headroom; treat it as an optional extractor for Office/HTML/image inputs and for table-structure assistance (Phase 4), never as the publish path for text-layer PDFs without our verifier passing.
- Any Docling output is accepted only through the same verification gate.

**Limits.** 5 pages of one document; table-cell accuracy was not scored here. Re-run on the Mac mini (Phase 6) and on Office/scan samples (Phase 4) before relying on it for those formats.
