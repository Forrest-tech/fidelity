# OCR on real NCC pages — VM, two engines (2026-11-18)

Same sample as `ocr-vm-rapidocr.md` (NCC 2025 Volume One pp. 120 and 450, 300 dpi, 6 degradations,
1400 px cap), now with both engines: RapidOCR (English model, angle classifier off) and Tesseract 5.4.
Correction rules active: confusables in numbers, `KN`→`kN`, `$17C7`→`S17C7` (clause IDs), glossary
(12,939 words learned from the 610 verified files in `/Transfer_Md`). Typographic variants (curly/straight
quotes, `--`/`—`) do not count as disagreement.

- **Recall 99.9%, numbers 100%** for RapidOCR on every condition (was 92–98% / 96–100% alone).
- **Page 450** (prose) is accepted automatically in 4 of 6 conditions. Its order-sensitive accuracy reads
  ~91% only because the running footer ("NCC 2025 Volume One … Page 450") is first in the PDF text layer
  and last in the OCR reading order; every word and number is present (checked word by word).
- **Page 120** (mostly a table) stays in review in every condition: the engines order table cells
  differently and differ on symbols (`10°` / `10'`). That is the intended outcome.
- The glossary made no difference on these two pages: the remaining disagreements are layout and
  symbols, not misread words.

---

Engines: rapidocr (en model), tesseract (eng model). Ground truth: text layer of `NCC 2025 Volume One.pdf`.

| Degradation | Pages | rapidocr: accuracy / recall / numbers | tesseract: accuracy / recall / numbers | Auto-accepted | Worst accepted page |
|---|---|---|---|---|---|
| blur | 2 | 76.1% / 99.9% / 100.0% | 77.0% / 99.1% / 96.7% | 1 | 91.62% |
| clean | 2 | 75.7% / 99.9% / 100.0% | 75.7% / 99.7% / 100.0% | 1 | 90.90% |
| combined | 2 | 75.0% / 99.9% / 100.0% | 75.0% / 98.3% / 100.0% | 0 | - |
| low_res | 2 | 75.8% / 99.9% / 100.0% | 77.1% / 99.0% / 96.7% | 1 | 90.90% |
| noise | 2 | 75.9% / 99.9% / 100.0% | 75.8% / 99.8% / 100.0% | 1 | 91.48% |
| skew | 2 | 74.1% / 99.9% / 100.0% | 75.9% / 99.6% / 97.0% | 0 | - |

Accuracy = 1 - edit distance / length (reading order counts). Recall = share of the ground truth's
letters and digits found anywhere on the page (order ignored). Numbers = share of numbers found.
Auto-accepted pages are published without review; all others go to the review queue.
