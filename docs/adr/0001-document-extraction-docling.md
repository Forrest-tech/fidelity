# ADR 0001: Docling versus the current extractor (Spike 1)

Date: 2026-11-17. Status: accepted.

**Question.** Can Docling replace or complement PyMuPDF for NCC-style text-layer PDFs, scored by our verifier, and does it run on the 4 GB VM (spec section 7, assumption 3)?

**Method.** 12 pages (4 consecutive pages from the middle of each of NCC 2025 Volume One, Two and Three; read-only source copies, slices in a scratch folder). Docling 2.150.1, CPU, default pipeline (layout + table models) in an isolated venv. Scored with the verifier's own measures (`app.distill.verify`): per-slice alphanumeric-character recall and number recall of the PyMuPDF source text (header/footer bands excluded) against the Docling Markdown.

**Results.**
| Measure | Docling | PyMuPDF pipeline |
|---|---|---|
| Character recall (verifier measure) | 100% on all 3 slices | 99.99% over 2,528 pages |
| Number recall | 100% on all 3 slices | 100% |
| Time | 128 s, 217 s, 142 s per 4 pages (32-54 s/page) | ~0.1 s/page |
| Peak memory | 0.8-1.0 GB (fits the 4 GB VM, one document at a time) | small |
| Install | torch + models, several GB | ~50 MB |
An earlier 5-page run scored a stricter word-token measure (94.1%) that is sensitive to formatting; it is not the verifier's measure and is not used for the decision.

**Decision.**
- Docling reaches the verifier's recall on text-layer pages, so it is a credible *second, independent extractor* and the preferred engine for formats PyMuPDF cannot read (Office, HTML, images) and for table structure (Phase 4).
- PyMuPDF stays primary for text-layer PDFs: ~300-500x faster (a 600-page volume would take about 6 hours in Docling), gives exact bookmarks, bounding boxes and font data that structure detection and the unit markers rely on.
- Docling output is accepted only through the same verification gate. Run one Docling job at a time on the VM.

**Limits.** 12 pages; the verifier measures are bag-of-characters, so they do not prove table cells sit in the right column (the new table-cell check, Phase 2) or reading order. Formula regions were not compared. Re-run on a scanned sample in Phase 4 and on the Mac in Phase 6.
