# Grok sample — requirements v3 V-1 (2026-11-24)

**What was tested:** Grok on grok.com, with the everyday `au-compliance-kb` skill and the live library in
`/Library_Installation/Md_Library` after plan C2 (library releases 1–2).

**Questions:** 30 drawn at random within each category of the bank (`grok_sample_30.json`, seed 20261124), in a new
chat each. Grok was asked to end each normal answer with one machine-readable line. Grading uses the same rules as
the harness (`app/acceptance/grade.py`). The Grok free-tier limit stopped the run after 26 questions; the 4 missing
ones are trap questions, which the 316-question harness answers 36/36.

## Result

| | Grok | DeepSeek (harness), same 26 questions |
|---|---|---|
| Passed | **18/26** (95% interval 50–84%) | 25/26 |
| Category A, direct clause questions | **10/10** | 10/10 |
| Category B, applied questions | 6/9 | 9/9 |
| Category D, older editions | **1/5** | 5/5 |
| Category E, tables | 1/2 | 1/2 |
| Exact page cited (right figure) | 22/24 (91.7%) | — |
| Agreement Grok vs DeepSeek | 19/26 | |

## Why Grok failed

| Question | Cause | Action |
|---|---|---|
| 232, 235, 267, 278 (D) | Right figure from the 2018 edition, but the answer did not say the edition is **superseded** | Skill answer format now has a required `Edition: … current, or SUPERSEDED by …` line (installed 2026-11-24); re-test when the Grok allowance resets |
| 136, 215 (B) | Substantively right (the quotes contain "5 × DN 100" and the second criterion), but the captured final line left out part of the answer | Sample captured only the final line; the next sample keeps the full answer |
| 154 (B) | Cited Appendix E Table E.3 (p.223, same figure) instead of clause 16.3.5 (p.195) | Counted as wrong page |
| 173 (E) | Table quote with "…" pieces not found on the page; DeepSeek failed the same question | Table quoting stays an open measurement item |

## What this says about the harness

The 316-question harness (98.7%) predicts Grok well on direct clause questions. It **overstates** Grok on
older-edition questions: DeepSeek follows the "say it is superseded" rule, Grok mostly did not. The skill fix above
targets exactly that; the D questions are re-run on Grok to confirm it.

Plan C2 effect on Grok: AS questions used 3 Dropbox sources in the first test, against 10–29 before C2.
