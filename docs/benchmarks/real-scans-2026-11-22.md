# OCR accuracy on real scans — 2026-11-22

Each scan is compared, page by page, with a native text PDF of the same edition held in the same room (`app/distill/evaluate.py`). Figures only; no standards text. Order-free measures lead: tables come out row by row from OCR and column by column from a text layer, so the character error rate mostly measures reading order.

| Edition | Copy | Read by | Pages compared | Word recall | Number recall | Extra numbers | Pages with every number | CER (order-sensitive) |
|---|---|---|---|---|---|---|---|---|
| AS/NZS 3500.1:2018 | 3500.1-2018  Plumbing and drainage - Water services.pdf | native text (another copy) | 119 of 129 | 100.0% | 100.0% | 0 | 119 | 0.0% |
| AS/NZS 3500.1:2021 | AS-NZS_3500.1-2021 Printed Converted to Searchable.pdf | another program's OCR layer | 119 of 136 | 95.0% | 93.2% | 830 | 13 | 15.2% |
| AS/NZS 3500.1:2021 | AS-NZS_3500.1-2021 Printed.pdf | our OCR (two engines) | 107 of 136 | 95.0% | 92.6% | 262 | 11 | 16.5% |
| AS/NZS 3500.2:2018 | 3500.2-2018_V3  Plumbing and drainage - Sanitary plumbing and drainage.pdf | our OCR (two engines) | 206 of 225 | 95.9% | 84.3% | 103 | 43 | 7.8% |
| AS/NZS 3500.3:2021 | AS-NZS_3500.3-2021 Printed Converted to Searchable.pdf | another program's OCR layer | 180 of 202 | 95.8% | 91.7% | 559 | 47 | 13.4% |
| AS/NZS 3500.3:2021 | AS-NZS_3500.3-2021 Printed.pdf | our OCR (two engines) | 176 of 202 | 94.7% | 89.3% | 294 | 56 | 14.1% |
