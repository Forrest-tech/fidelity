# Page audit round 2: Phase E (usability), 2026-11-22

**Method.** A cognitive walkthrough of the first-use task, "from nothing to an accepted file in the output folder". It was done as a new reviewer and as an administrator, on an isolated copy of the live data (port 8782), together with the questions the owner actually asked on 2026-11-22. Scoring follows the rubric in [FINDINGS.md](FINDINGS.md); only options scoring **9.5 or more** were implemented.

| ID | Where | Finding | Fix (alternatives) | Score | Outcome | Test |
|---|---|---|---|---|---|---|
| E-01 | Overview, Distill | A first-time user sees "No rooms yet" and has to work out on their own that storage must be connected first, then a room made with two folders, run, and the results accepted. W-02 from round 1 noted the same problem. | A **Get started** checklist. Each step ticks itself off from the real state (storage connected, a room with both folders, a finished run, an accepted file) and offers the button for the next step. It hides itself when everything is done or when the user hides it. (A one-off tour: 8.4, people skip it and it doesn't come back. Empty-state buttons only: 8.5, they cover one step.) | 9.6 | Fixed | guide.test (4) |
| E-02 | Distill | The owner had to ask what "copy-protected", "duplicate", "skipped" and "download failed" meant. Each state is explained only in a tooltip on one file at a time. | **What do these mean?** next to the state legend. It opens one table: every state, what it means, what to do; then every reason. (Tooltips only, as before: 8.0. A help page: 8.9, it takes the user away from the files.) | 9.6 | Fixed | distill.test |
| E-03 | Settings → System health | "5.8 MB · 2019" looks like a year. It is the number of files. | "5.8 MB · 2019 files" | 9.6 | Fixed | system.test |
| E-04 | Settings → System health | "Running for 0 hours" straight after a restart | Minutes below one hour | 9.5 | Fixed | — |
| E-05 | All | No notice when a long run finishes unless the page is watched | Browser notification on finish | 9.0 | Recorded: the bell already shows it; browser permission prompts per machine | — |
| E-06 | All | No e-mail notifications (U-4) | SMTP e-mail on finish, failure or review | 8.0 | Recorded: needs a company SMTP account and its password | — |

**Not possible here.** The 5-person usability test with SUS scoring (requirements v2, U-2) needs colleagues who have never used the system. It stays on the list for when the owner can arrange it; this walkthrough stands in for it until then.
