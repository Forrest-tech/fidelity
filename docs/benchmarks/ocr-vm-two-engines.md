# OCR synthetic-scan benchmark — VM, two engines (2026-11-18)

Windows 10 VM (4 GB). RapidOCR 1.2.3 with the PP-OCRv3 **English** recognition model (pinned, SHA-256
checked, fetched by `scripts/fetch_ocr_models.py`) and the 0/180° line classifier **off**; Tesseract 5.4.0
(UB Mannheim build, `eng`). Reproduce: `python scripts/ocr_benchmark.py --synthetic --out <dir>`.

What changed against `ocr-vm-rapidocr.md` (RapidOCR alone, default Chinese model, 72–96%):

- The angle classifier flipped the longest line on each page and turned it into garbage (one line lost per
  page, recall ~90%). With it off, RapidOCR reads 99.8–100%.
- `KN`/`KPa` after a number is corrected to `kN`/`kPa` (logged); spacing-only differences between the
  engines ("25 m." / "25m.") no longer count as disagreement.
- 11 of 18 pages are now accepted automatically (worst accepted page 99.81% accuracy). The rest go to
  review because the engines differ on real characters (e.g. `Ioad` / `load`), or — for skewed pages —
  Tesseract drops digits. That is the intended behaviour.

The synthetic source PDF is regenerated on every run and is not kept.

---

Engines: rapidocr (en model), tesseract (eng model). Ground truth: text layer of `ocr-vm-two-engines.source.pdf`.

| Degradation | Pages | rapidocr: accuracy / recall / numbers | tesseract: accuracy / recall / numbers | Auto-accepted | Worst accepted page |
|---|---|---|---|---|---|
| blur | 3 | 100.0% / 100.0% / 100.0% | 99.8% / 100.0% / 100.0% | 2 | 100.00% |
| clean | 3 | 100.0% / 100.0% / 100.0% | 99.8% / 100.0% / 100.0% | 2 | 100.00% |
| combined | 3 | 99.8% / 100.0% / 100.0% | 99.6% / 99.8% / 94.6% | 2 | 99.81% |
| low_res | 3 | 100.0% / 100.0% / 100.0% | 99.8% / 100.0% / 100.0% | 2 | 100.00% |
| noise | 3 | 100.0% / 100.0% / 100.0% | 99.8% / 100.0% / 100.0% | 3 | 100.00% |
| skew | 3 | 100.0% / 100.0% / 100.0% | 99.6% / 99.9% / 95.5% | 0 | - |

Accuracy = 1 - edit distance / length (reading order counts). Recall = share of the ground truth's
letters and digits found anywhere on the page (order ignored). Numbers = share of numbers found.
Auto-accepted pages are published without review; all others go to the review queue.
