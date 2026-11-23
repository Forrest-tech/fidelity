# AI reading arbitration measured against known truth — 2026-11-22

**What was measured.** Where our two OCR engines disagreed on a real scan, DeepSeek (`deepseek-chat`) was asked to choose a reading. It used the live `arbitrate` skill's prompt and rules: choose one candidate or answer "uncertain", and never write a new reading. The same edition also exists in the room as a native text PDF, so each case is decided by which candidate appears on the matching native page. Cases where both candidates or neither appear there are left out. Reproduce with `backend/scripts/eval_arbitration.py`; the raw figures are in the two JSON files next to this one.

| Scan (truth: the native PDF of the same edition) | Kind | Cases | Right / wrong / uncertain | Accuracy when it chose | At confidence ≥ 0.9 |
|---|---|---|---|---|---|
| AS/NZS 3500.3:2021 printed | words | 33 | 26 / 5 / 2 | 83.9% | 93.8% (15 of 16) |
| AS/NZS 3500.3:2021 printed | numbers | 26 | 23 / 3 / 0 | 88.5% | 100% (13 of 13) |
| AS/NZS 3500.1:2021 printed | words | 42 | 38 / 2 / 2 | 95.0% | 100% (24 of 24) |
| AS/NZS 3500.1:2021 printed | numbers | 14 | 11 / 2 / 1 | 84.6% | 100% (5 of 5) |
| **Both** | **words** | **75** | **64 / 7 / 4** | **90.1%** | **97.5% (39 of 40)** |
| **Both** | **numbers** | **40** | **34 / 5 / 1** | **87.2%** | **100% (18 of 18)** |

**Reading the figures.** Even at high confidence there was one wrong word in 40. With samples this small, the true word error rate at ≥ 0.9 could be anywhere from about 0.5% to 13% (95% interval); 18 correct number cases are too few to support any claim. Neither reaches the 99% target, so the AI may not write into results by itself.

**Decision.** Arbitration is switched on at **level 2**: after every run the AI suggests a reading for each doubtful place, and a person accepts or rejects it. The reviewer sees the choice and its confidence, which turns a long list of doubtful places into a quick confirmation pass. Level 3 (automatic adoption, plain words only, never numbers) stays locked until `ai/level3.py`'s gate is met: 300 suggestions decided by people with at least 98% taken, and no sampled adoption found wrong in 90 days.

**Ways to raise accuracy later.** Give the arbiter the page image (DeepSeek's API reads text only; a vision model would). Add a third OCR engine on the Mac mini. Re-measure with this script before any change of level.
