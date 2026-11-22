# Fidelity web app: test cases

Plan and method: [TEST_PLAN.md](TEST_PLAN.md). Findings and fixes: [FINDINGS.md](FINDINGS.md).

Columns: **Data** = R real, B boundary, X bad input, N network failure, L language, S screen size, A role/access.
**Auto** = where the case is automated (`api:` backend pytest file, `unit:` Vitest file, `e2e:` Playwright spec)
or `manual` (exploratory, result recorded in FINDINGS.md).
Every page is also covered by the cross-cutting cases at the end (accessibility, responsive, both themes).

## LOGIN: sign-in and first-run set-up (`/login`)

| ID | Case | Data | Expected | Auto |
|---|---|---|---|---|
| LOGIN-01 | Open the page | R | Heading "Sign in to Fidelity", configured SSO buttons, "or", email focused, password masked, bot check passes by itself | e2e:login.spec |
| LOGIN-02 | Submit empty / spaces-only / malformed email | B X | Field messages under each field; no request sent | e2e:login.spec |
| LOGIN-03 | Wrong password, then right password | R X | "Wrong email or password"; second try works with a fresh bot check | e2e:login.spec, unit:shell |
| LOGIN-04 | Keyboard only; email with spaces around it | B | Enter submits; spaces ignored | e2e:login.spec |
| LOGIN-05 | Deep link while signed out | R | Back to the requested page after sign-in | e2e:login.spec |
| LOGIN-06 | Connection lost / server error during sign-in | N | "Check your connection"; typed email kept | e2e:login.spec |
| LOGIN-07 | Forgot password | R | Explains that an administrator resets it | e2e:login.spec |
| LOGIN-08 | Chinese | L | Page, validation and errors in Chinese | e2e:login.spec |
| LOGIN-09 | Phone width | S | One column, no sideways scroll, full-width buttons | e2e:login.spec |
| LOGIN-10 | SSO as a registered person | R | One click, lands on the requested page, session works | e2e:login.spec, api:test_login_security |
| LOGIN-11 | SSO as an unregistered person | X | "Not registered in Fidelity, ask an administrator"; stays signed out; URL cleaned | e2e:login.spec, api |
| LOGIN-12 | SSO with unverified email; cancel at provider | X | Refused with the reason; "Sign-in was cancelled" | e2e:login.spec, api |
| LOGIN-13 | Plain-HTTP office address (no HTTPS) | R | Bot check still passes; sign-in works | e2e:login.spec |
| LOGIN-14 | 5 wrong passwords from one address; 6th with right password | B | 429 "Too many failed attempts", Retry-After | api, unit:shell |
| LOGIN-15 | 10 wrong passwords for one account from 10 addresses | B | Account locked for 15 min; other accounts unaffected | api |
| LOGIN-16 | Bot check missing / reused / tampered / wrong / expired / oversized | X B | Refused with a specific reason; does not count as a wrong password | api |
| LOGIN-17 | 61 sign-in endpoint calls in a minute | B | 61st is 429 | api |
| LOGIN-18 | Forged OAuth state, missing cookie, open redirect in `next`, provider down | X N | Back to sign-in with a reason; never redirected off-site | api |
| LOGIN-19 | Inactive user (password and SSO) | A | Refused | api |
| LOGIN-20 | First run: create administrator; passwords differ; under 10 characters; set-up already done | B X | Mismatch and length shown under fields; signed in after creation; 409 after the first user | unit:pages, api:test_storage_setup |
| LOGIN-21 | Unusual usernames (empty, 400 chars, SQL text, non-Latin) | X B | Plain refusal, no error page | api |
| LOGIN-22 | Sign out | R | Session ends; back to sign-in; API calls 401 | e2e:app.spec, api |

## SHELL: top bar, navigation, search, notifications (every signed-in page)

| ID | Case | Data | Expected | Auto |
|---|---|---|---|---|
| SHELL-01 | Navigate with the top bar (desktop) and bottom bar (phone) | S | Each link opens its page; current page marked | e2e:app.spec |
| SHELL-02 | Command palette Ctrl/Cmd+K, type, Enter | R | Goes to the page / runs the action | e2e:app.spec |
| SHELL-03 | Switch language; reload | L | Whole interface translated; choice remembered; `<html lang>` updated | e2e:app.spec, unit:shell |
| SHELL-04 | Dark mode toggle; reload | R | Dark everywhere incl. review screen; remembered | e2e:app.spec |
| SHELL-05 | Notifications: open, mark all read, open one | R | Goes to the linked page; unread count drops | unit:level3 |
| SHELL-06 | Session expires while using a page | N | Sent to sign-in, then back to the page | manual |
| SHELL-07 | Unknown address | X | Back to Overview | e2e:app.spec |

## OVR: Overview (`/`)

| ID | Case | Data | Expected | Auto |
|---|---|---|---|---|
| OVR-01 | New installation | B | Empty state that says what to do first | unit:shell |
| OVR-02 | With rooms and runs | R | Counts and recent activity match the Distill and Results pages | api:test_overview_api |
| OVR-03 | API error | N | Error state with Try again | unit |

## DST: Distill rooms (`/distill`)

| ID | Case | Data | Expected | Auto |
|---|---|---|---|---|
| DST-01 | Create a room: name, input (read-only source), output place, mode; Save | R | Room listed; draft gone | unit:distill, api:test_rooms |
| DST-02 | Draft: leave the page with unsaved changes | R | Leave-page guard asks; draft restorable | unit:distill |
| DST-03 | Name empty / 1 char / very long / Chinese / HTML text | B X L | Empty refused with a message; long kept readable; text shown literally | unit:distill, api |
| DST-04 | Input and output overlap or output inside the source | X | Refused, explained ("overlap") | unit:distill, api |
| DST-05 | Start a run; watch per-file stages; finished | R | Each file shows its step; totals right; notification | api:test_rooms, unit:distill |
| DST-06 | Duplicate files, protected (password) PDFs, unsupported files | R X | Marked skipped / duplicate, not failures, with the reason | unit:distill, api:test_rooms |
| DST-07 | Run interrupted (server restart) | N | Shown as interrupted; Resume continues | api:test_run_supervision |
| DST-08 | Queue: two rooms; priority; capacity | B | Second waits; order follows priority | api:test_queue_claim |
| DST-09 | Accept results below threshold; compare with live; roll back | R | Confirm step states impact; rollback restores | unit:distill, api:test_accept |
| DST-10 | Viewer | A | Sees rooms; no create/start/accept buttons | e2e:app.spec, api |

## DOC: Results (`/documents`) and REV: Review (`/review`)

| ID | Case | Data | Expected | Auto |
|---|---|---|---|---|
| DOC-01 | No results yet | B | Says what to do | unit:pages |
| DOC-02 | Filter by status, open a file | R | Opens in its room; filter kept | unit:pages |
| REV-01 | Open review, switch language and theme | L | Follows the shell language and dark theme; accessible | e2e:app.spec |
| REV-02 | Compare source and Markdown, fix a cell, record a decision | R | Decision saved and listed | unit:level3, api |

## SRC: Sources (`/sources`) and JOB: Jobs (`/jobs`)

| ID | Case | Data | Expected | Auto |
|---|---|---|---|---|
| SRC-01 | Empty / data / error-with-retry | B N | Each state clear | unit:shell |
| SRC-02 | Distill all PDFs (reviewer); viewer has no button | A | Job queued; viewer cannot | e2e:app.spec, unit:pages |
| SRC-03 | Dropbox sync: dry run first, then run, rollback (admin) | R | Dry run default; plain-language errors | api:test_dropbox_sync_api, unit:pages |
| JOB-01 | Jobs list empty / running / failed | B | Status words, not codes | unit:pages |

## SET: Settings (`/settings/*`) and USR: Users

| ID | Case | Data | Expected | Auto |
|---|---|---|---|---|
| SET-01 | Account: change password (wrong current, short new, success) | X B | Messages; new password works, old does not | api:test_app_ui |
| SET-02 | Appearance and language | L | Applies at once, remembered | e2e:app.spec |
| SET-03 | Cloud storage (admin): connect Dropbox / Google Drive | R | Shows the provider link; non-admin cannot see | unit:pages, api:test_storage_setup |
| SET-04 | AI settings (admin): add key, budget | X | Key stored encrypted; never shown again | api:test_ai, unit:ai |
| SET-05 | Defaults, queue, corrections, archive, notifications, audit | R | Each loads, saves, shows empty state | unit:level3, api |
| USR-01 | Add a user: valid, duplicate email, short password, bad email | X B | Created; clear message for each problem (not a code) | e2e:app.spec, api:test_auth |
| USR-02 | Non-admin opens Users | A | "No access" | e2e:app.spec, unit:shell |

## X: cross-cutting, every page

| ID | Case | Expected | Auto |
|---|---|---|---|
| X-01 | axe WCAG 2.1 A/AA, light and dark | No violations | e2e:app.spec, stories-check |
| X-02 | Desktop 1280, tablet 768, phone 375 | No sideways scroll; navigation reachable | e2e:app.spec |
| X-03 | English and Chinese | No untranslated text, no raw keys | e2e:app.spec, manual audit |
| X-04 | Console and network | No console errors, no unexpected 4xx/5xx | manual audit |
| X-05 | Visual | No unintended change against Linux baselines | e2e:app.spec |
| X-06 | Lighthouse on sign-in | Performance, accessibility, best practices meet the CI budget | CI frontend-build |
