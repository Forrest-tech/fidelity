# OCR synthetic-scan benchmark - development VM (2026-11-18)

Machine: 4 GB Windows VM, CPU only. Only RapidOCR is installed here (no Tesseract binary), so no page
can be cross-checked and **every scanned page goes to the review queue by design**. Sample: 2 pages of
NCC 2025 Volume One (pp. 120 and 450) rendered at 300 dpi, 6 degradations, images capped at 1400 px.
Finding: RapidOCR alone does not reach Q-1 (99 % characters, 100 % numbers) on these pages; this is the
expected result for the VM and the reason scans are reviewed until the Mac engines (Phase 6) are measured.
CI runs the same benchmark with both engines on a synthetic document (artifact `ocr-benchmark`).


Engines: rapidocr. Ground truth: text layer of `NCC 2025 Volume One.pdf`.

| Degradation | Pages | rapidocr: accuracy / recall / numbers | Auto-accepted | Worst accepted page |
|---|---|---|---|---|
| blur | 2 | 73.1% / 96.8% / 98.9% | 0 | - |
| clean | 2 | 73.1% / 98.2% / 98.9% | 0 | - |
| combined | 2 | 70.6% / 97.7% / 100.0% | 0 | - |
| low_res | 2 | 72.1% / 95.2% / 98.9% | 0 | - |
| noise | 2 | 68.8% / 92.2% / 96.3% | 0 | - |
| skew | 2 | 72.3% / 92.1% / 98.9% | 0 | - |

Accuracy = 1 - edit distance / length (reading order counts). Recall = share of the ground truth's
letters and digits found anywhere on the page (order ignored). Numbers = share of numbers found.
Auto-accepted pages are published without review; all others go to the review queue.
