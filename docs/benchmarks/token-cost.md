# Token cost of the library layout — /Transfer_Md (NCC 2025, 5 documents), 2026-11-18

610 files. Tokens estimated as characters / 4; listing cost 330 tokens per entry (Grok Dropbox connector, measured).

| Per file | min | p5 | median | p95 | max |
|---|---|---|---|---|---|
| tokens | 290 | 331 | 1,778 | 10,195 | 21,632 |

- In the 10k–30k target: **5%**; below: 95%; above: 0%.
- Listing a folder: median 2,640 tokens, largest 16,500 tokens.

Largest files:

- 21,632 — `2025/ss/NCC 2025 preview draft – Volume One/14 Section J Energy efficiency/NCC 2025 preview draft – Volume One · 096 Part J3 Elemental provisions for a Class 4 part of a building [J3D1–J3D15] p483-514.md`
- 21,446 — `2025/NCC 2025 Volume One/15 Section J Energy efficiency/NCC 2025 Volume One · 097 Part J3 Elemental provisions for a Class 4 part of a building [J3D1–J3D15] p492-523.md`
- 16,603 — `2025/ss/NCC 2025 preview draft – Volume One/NCC 2025 preview draft – Volume One · 005 Copyright, Licence Notice and Acknowledgment of Country (part 4 of 8) p22-27.md`
- 16,346 — `2025/ss/NCC 2025 preview draft – Volume One/NCC 2025 preview draft – Volume One · 004 Copyright, Licence Notice and Acknowledgment of Country (part 3 of 8) p16-21.md`
- 16,069 — `2025/ss/NCC 2025 preview draft – Volume One/NCC 2025 preview draft – Volume One · 003 Copyright, Licence Notice and Acknowledgment of Country (part 2 of 8) p10-15.md`
- 15,951 — `2025/ss/NCC 2025 preview draft – Volume One/16 Schedule 2 Referenced documents/NCC 2025 preview draft – Volume One · 124 Referenced documents p642-660.md`
- 15,602 — `2025/NCC 2025 Volume One/NCC 2025 Volume One · 005 Copyright, Licence Notice and Acknowledgment of Country (part 4 of 8) p20-25.md`
- 15,343 — `2025/NCC 2025 Volume One/NCC 2025 Volume One · 004 Copyright, Licence Notice and Acknowledgment of Country (part 3 of 8) p14-19.md`
- 15,078 — `2025/NCC 2025 Volume One/NCC 2025 Volume One · 003 Copyright, Licence Notice and Acknowledgment of Country (part 2 of 8) p8-13.md`
- 14,954 — `2025/ss/NCC 2025 preview draft – Volume One/08 Section C Fire resistance/NCC 2025 preview draft – Volume One · 033 Specification 5 Fire-resisting construction [S5C1–S5C25] p163-181.md`

## Reading (2026-11-18)

- Files are **smaller** than the Q-3 target: chapters are split per Part, so a typical read is ~1.8k tokens
  and none exceeds 30k. Each read is cheap.
- The cost moves to **navigation**: a typical answer lists the document folder (~26 entries, ~8.6k tokens)
  and one Section folder (~2.6k), then reads one file (~1.8k): about **13k tokens**, within "a few listings
  and one read". Search by file name can skip the listings.
- Open question (spec assumption 4): whether merging small Parts into ~10k-token files lowers the total
  (fewer entries to list) without hurting accuracy. Decide in the acceptance trial by running the same
  questions against both layouts; until then the threshold stays as it is.
