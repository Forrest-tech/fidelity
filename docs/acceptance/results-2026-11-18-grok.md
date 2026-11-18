# Acceptance run 1 — Grok, 2026-11-18 (partial)

Setup: Grok (Fast), Dropbox connector, one private chat per question, the regenerated pack
(`adapters/dist/grok/au-compliance-kb.md`) pasted as instructions, library `/Transfer_Md` (NCC 2025,
new format), no answer key given to the tool. Questions from `question_bank.json` v2 in order.

**Stopped at question 28 by Grok's free-tier limit**; the owner then paused tool testing until the
remaining development is finished. Q26 hit a Dropbox connector outage (HTTP 503) — the tool correctly
refused to answer from memory; it is re-run, not scored.

## Result: 26 of 26 answered questions pass

| Q | Cat | Result | Notes | Seconds |
|---|---|---|---|---|
| 1 | A | PASS | 190 / 115 mm, D3D14, p.241 | 40 |
| 2 | A | PASS | going 240–355, 2R+G 550–700 | 39 |
| 3 | A | PASS | 30 m, D2D5 | 38 |
| 4 | A | PASS | 2.4 m, F5D2(1)(c), p.374 | 65 |
| 5 | A | PASS | 8 000 m², Table C3D3 | 157 |
| 6 | A | PASS | 45 °C, B2D5(a)(iii) | 79 |
| 7 | A | PASS | Flashover 1 MW, glossary p.633 | 118 |
| 8 | A | PASS | 6 mm, TAS C4D12 | 118 |
| 9 | B | PASS | E1D5 and E1D6(1) | 41 |
| 10 | B | PASS | 2 exits, D2D3(2)(a)(i) | 31 |
| 11 | B | PASS | Performance Solution definition | 77 |
| 12 | B | PASS | sole-occupancy unit definition | 69 |
| 13 | B | PASS | 45 °C, B2D5(a)(iv) | 59 |
| 14 | B | PASS | private stairways, Table D3D14 notes | 101 |
| 15 | C | PASS | 6 m / 20 m + definition | 67 |
| 16 | C | PASS | plant-only storey excluded, glossary + E1D6 | 58 |
| 17 | G | PASS | "deletes D3D14(1) and inserts NSW D3D14(1)" (was PARTIAL in Phase 0) | 73 |
| 18 | C | PASS | Vol Two refers to Housing Provisions Part 11.2 (H5D2) | 55 |
| 19 | D | PASS | 2.4 m from published p.374 | 57 |
| 20 | D | PASS | PCD objective quoted, "not in force" | 46 |
| 21 | D | PASS | preview draft not in force | 41 |
| 22 | D | PASS | published authoritative | 67 |
| 23 | E | PASS | 550–700 | 70 |
| 24 | E | PASS | 20 m / 40 m, D2D5(3)(a) | 46 |
| 25 | E | PASS | 4 or more and ≤ 25 m | 36 |
| 27 | F | PASS | "Not found", search terms listed, nothing invented | 45 |

Median time 59 s, maximum 157 s (Phase 0: 6–74 s "thinking" on the old layout; times here are wall-clock
including retrieval). Every answer named the chapter file, clause and page; no hallucinated value.

## Still to run
Q26 and Q28–Q100 (Grok when the limit allows, or another tool), then the layout comparison
(plan §4.4). The runner keeps the answers in the browser and resumes from the first unanswered question.
