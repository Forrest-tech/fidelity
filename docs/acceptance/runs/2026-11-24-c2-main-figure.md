# Acceptance run

Graded by fixed rules (`app/acceptance/grade.py`): figure and unit right, citation's quote found on the cited page of the original PDF (±1 page), edition status stated for superseded editions, traps refused. 95% interval: Wilson.

| Run | Passed | Rate | 95% interval | Traps | Failures: search missed the page / answer wrong | Not answered (call failed) |
|---|---|---|---|---|---|---|
| C2 library, DeepSeek reasoner, main-figure rule | 308/316 | 97.5% | 95.1%–98.7% | 36/36 | 1 / 7 | 0 |

## By category

| Category | C2 library, DeepSeek reasoner, main-figure rule |
|---|---|
| A | 108/109 |
| B | 104/107 |
| D superseded edition | 47/49 |
| E | 13/15 |
| F trap: clause does not exist | 12/12 |
| F trap: edition not held | 9/9 |
| F trap: false premise | 15/15 |

## Failures — C2 library, DeepSeek reasoner, main-figure rule (8)

- **Q94** (E) Under AS/NZS 3500.2:2021, what is the minimum grade for a DN 100 graded discharge pipe as given in Table 6.6.1?  
  expected: 1.65% — AS/NZS 3500.2:2021 cl. 6.6.1 p.86  
  got: Under AS/NZS 3500.2:2021, Clause 6.6.1 provides that 'The minimum grades of discharge pipes shall be in accordance with Table 6.6.1.' In Table 6.6.1 — Minimum grades of discharge pipes, the DN 100 graded section of pipe has a minimum grade of 1.65%. (The table lists the DN 80/100/125/150 row as 1.65  
  why: citation not on the cited source page (answer)
- **Q113** (B) Under AS/NZS 3500.2:2021, when sizing branch vents, what is the minimum DN for a branch vent that connects to a DN 40 group vent?  
  expected: DN 40 — AS/NZS 3500.2:2021 cl. 8.5.2.3 p.114  
  got: Under AS/NZS 3500.2:2021 the minimum size of a branch vent is set by the size of the branch DISCHARGE pipe it serves, not by the size of the group vent it connects to; the library contains no rule that sizes a branch vent from the DN of the group vent. Clause 8.5.2.1 states: 'The size of any branch   
  why: main figure is not the page's (answer)
- **Q146** (B) Under AS/NZS 3500.2:2021, when connecting a pumped waste discharge from a swimming pool through a gully, what is the minimum depth between finished surface level and the invert level?  
  expected: 75 mm min. — AS/NZS 3500.2:2021 cl. 12.8.7 p.177  
  got: Clause 12.8.7 (p.176) requires the pump discharge pipe from waste fixtures or swimming pools to be 'connected in accordance with Clause 12.7, or connected to a gully riser, as shown in Figure 12.8.7(A) or Figure 12.8.7(B)'. Figure 12.8.7(B) — 'Connection of pumped waste discharge from swimming pools  
  why: main figure is not the page's (answer)
- **Q164** (A) Under AS/NZS 3500.2:2021, Clause 16.10.4, for a vacuum automatic interface unit with a second stage lift above 900 mm, what is the maximum first stage lift permitted?  
  expected: Max. 2 m — AS/NZS 3500.2:2021 cl. 16.10.4 p.203  
  got: Clause 16.10.4 does not itself state a single numeric 'first stage lift' height; it makes the first stage lift comply with Clauses 16.10.1, 16.10.2 and 16.10.3: "When a branch line incorporates a second stage lift, the first stage lift shall be in accordance with Clauses 16.10.1, 16.10.2 and 16.10.3  
  why: main figure is not the page's (answer)
- **Q173** (E) Under AS/NZS 3500.2:2021, when vacuum testing a DN 300 vacuum drainage pipe over a 250 m test length, what is the minimum test duration?  
  expected: 23 min — AS/NZS 3500.2:2021 cl. 16.15.3 p.208  
  got: Table 16.15.3 of AS/NZS 3500.2:2021 gives the minimum test duration for vacuum testing of vacuum drainage systems. For a DN 300 pipe over a 250 m test length, the table row '225 / 300' under 'Test length m — 250' shows 13 min for DN 225 and 23 min for DN 300, so the minimum test duration is 23 min.   
  why: citation not on the cited source page (answer)
- **Q182** (B) Under AS/NZS 3500.3:2021, when sizing the downpipes on a roof drainage system, what is the smallest permissible diameter of a round downpipe and the smallest permissible size of a rectangular downpipe?  
  expected: At least 90 mm diameter, or 100 mm × 50 mm rectangular — AS/NZS 3500.3:2021 cl. 3.7.8 p.50  
  got: The excerpts give two different figures depending on the part of the roof drainage system being sized, and the general minimum clause itself (Clause 3.5.3 Vertical downpipes, p.35) is named in the excerpt but its text was not supplied.

(a) Eaves gutter systems — Table 3.5.2 (Required size of vertic  
  why: main figure is not the page's (answer)
- **Q262** (D superseded edition) For a holding tank vent in AS 3500.2:2018, what is the minimum vent size and how far above the waste inlet must the vent be positioned?  
  expected: DN 50 and 100 mm — AS 3500.2:2018 cl. 12.8.6 p.166  
  got: For a holding tank under AS/NZS 3500.2:2018, Clause 12.8.6 'Venting' requires a vent of minimum size DN 50, conforming with the venting requirements for waste fixtures, positioned a minimum of 100 mm above the waste inlet. Note: the excerpt's edition_status is 'superseded' — the library's latest hel  
  why: citation not on the cited source page (answer)
- **Q266** (D superseded edition) For box gutter fasteners under AS 3500.3:2018, what is the maximum spacing and minimum edge distance?  
  expected: 40 mm centres and 10 mm from edges — AS 3500.3:2018 cl. 4.7.2.3 p.52  
  got: Not found in the knowledge base. The excerpts supplied are all from AS/NZS 3500.3:2018 Section 3 (roof drainage design, box gutter general method and flow charts, Clause 3.7.4), Appendix I (sump/side overflow device, Figure I5) and Appendix J (worked examples J2–J4), plus the Section 1 symbols/units  
  why: figure wrong or missing; citation not on the cited source page; edition status not stated (library search: the page was not among the excerpts)
