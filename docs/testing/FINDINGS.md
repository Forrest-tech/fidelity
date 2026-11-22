# Page audit: findings, scores and fixes (round 1, 2026-11-22)

Method: [TEST_PLAN.md](TEST_PLAN.md) section 5. Each option was scored 0-10 on user value (30%),
correctness/risk (25%), consistency with the rest of the app (20%), effort (15%) and maintainability
(10%). Only options scoring **9.5 or more** were implemented; the rest are recorded with the reason.

Environment: isolated instance of the branch on port 8790 (own data folder and database, test users, a
local OpenID Connect provider, a copy of a real AS 3500 PDF), Chromium via Playwright and the in-app
browser. Automated sweep: 2 roles x 2 languages x desktop/phone x 19 pages = 114 page views, each checked
with axe-core (WCAG 2.1 A/AA), horizontal overflow, console errors, failed API calls, untranslated
text and small touch targets.

Automated sweep result: **0 axe violations, 0 horizontal overflow, 0 console errors, 0 unexpected API
failures.** Chinese in the English interface only where expected (the 中文 language button and user data
such as a source name); no raw translation keys.

## Scorecard

| ID | Page | Finding | Chosen fix (alternatives considered) | Score | Outcome | Test |
|---|---|---|---|---|---|---|
| L-01 | Sign-in | Plain, non-standard sign-in window; no SSO; no bot protection | Split-layout sign-in (antd), Google/Microsoft/GitHub/OIDC via httpx-oauth + FastAPI Users, ALTCHA, `limits` rate limits (alt.: Authlib — would duplicate FastAPI Users' account linking, 8.9; Cloudflare Turnstile — third-party script and calls, fails offline, 8.4; reCAPTCHA — tracking, 7.5) | 9.8 | Fixed | api:test_login_security, e2e:login.spec |
| L-02 | Sign-in | The live server is used as `http://10.0.0.150:8000` (plain HTTP, found in its access log). WebCrypto does not exist there, so the stock ALTCHA widget refuses to run: **nobody could have signed in** | Invisible check: ALTCHA solver (`altcha/lib`) with @noble/hashes key derivation, no WebCrypto needed (alt.: require HTTPS first — right long-term, but blocks today's users, 8.0; switch the check off on HTTP — no protection, 6.0) | 9.9 | Fixed | e2e LOGIN-13 (non-secure context) |
| L-03 | Sign-in | 60 calls/min on sign-in endpoints throttled a busy browser (CI) and would throttle an office behind one proxy | 300/min, configurable, the read-only options call not counted | 9.6 | Fixed | api: throttle tests |
| L-04 | Sign-in | First-run setup needed a second bot check to sign in after creating the admin | Setup signs the new administrator in directly | 9.5 | Fixed | api: test_first_run_setup_signs_the_new_admin_in |
| L-05 | Sign-in | Pressing Sign in just as the bot check finished could leave the form waiting 30 s and then say the check failed (antd validates asynchronously, so the submit ran with an older render's "not ready" value). Found by repeating the e2e runs | Read the latest proof from a ref, not from render state | 9.7 | Fixed | e2e LOGIN-03..06 x4 repeats, desktop+tablet: 32/32 |
| F-01 | Users | Could only add people: no role change, no switching off, no password reset — while the sign-in page tells people an administrator resets passwords. The library's PATCH needed a "superuser" flag Fidelity's admins never have, so it always returned 403 | Inline role select, Active switch, "Set password" dialog, sign-in methods shown, admin-role endpoint `PATCH /admin/users/{id}`; you cannot change yourself; the last active administrator cannot be demoted or switched off; error codes shown as sentences (alt.: separate edit page, 8.6) | 9.8 | Fixed | api: 3 tests; unit: pages.test; e2e F-01 |
| F-02 | Review | Viewers saw Batch score, Re-run all, Upload, Manage, verdict buttons — all refused by the server (403) | Hide changing controls for viewers, as the Sources page already does | 9.6 | Fixed | e2e F-02 |
| F-03 | Review | Threshold value "90%" covered by the "Mark passing" button; search icon over the placeholder | Wrap the button to its own line when narrow; keep the input's icon padding | 9.6 | Fixed | e2e F-03 |
| F-04 | Sources | A source whose folder does not exist on this server (the shipped default points at another computer) still offered "Distill all PDFs" | API reports `available`; the card says the folder is missing and hides start/upload | 9.5 | Fixed | e2e F-04 |
| F-05 | Distill | A reviewer could fill in a new room and only then, in a 5-second folder dialog, read "connect it in Settings" — which only an administrator can do | Notice in the draft at once; admin gets a link to Settings → Cloud storage, others "ask an administrator"; read-only `/cloud/ready` | 9.5 | Fixed | unit: distill.test; e2e F-05 |
| F-06 | Distill, Settings | "Capacity 1 points" | i18next plurals | 9.6 | Fixed | unit (translation keys) |
| F-07 | Review, no-access page | No page heading (screen-reader users navigate by headings) | Visually hidden `<h1>` | 9.5 | Fixed | unit: shell.test; e2e F-02 |
| F-08 | CI | Draft-room unit test checked the Save button before state settled (flaky in CI) | Wait for the button | 9.5 | Fixed | unit: distill.test |
| W-01 | Review | The reviewer name list defaults to a configured name, not the signed-in person | Default to the signed-in user's name when it is in the list | 9.0 | Recorded: needs a decision on how reviewer names map to accounts | — |
| W-02 | Distill, Overview | Empty states have no button of their own ("No rooms yet") | Button inside the empty state | 8.5 | Recorded: "+ New room" is already at the top right of the same screen | — |
| W-03 | Users | An account made by SSO from an allowed domain shows "Password" though nobody knows that password | Show "Password" only when one was set by a person | 8.8 | Recorded: needs a schema flag; harmless (the random password is unusable) | — |
| W-04 | Sources | The shipped default local source points at a developer's folder | Ship no default source; show the empty state | 9.2 | Recorded: live installation has its own config; F-04 already removes the dead end | — |
| W-05 | All | Main JS bundle 1.5 MB (500 kB gzip) | Split antd-heavy pages with lazy routes | 8.7 | Recorded: Lighthouse budget still met; larger change | — |
| W-06 | Settings | Users exists twice (/users and /settings/users) | Redirect /users to /settings/users | 8.0 | Recorded: both work and share one component | — |

## Not testable here, and why
* Full distill runs with the real AS 3500 / NCC PDFs: this machine had about 300 MB of free memory with
  the live server running; a run could have starved it. Runs are covered by the backend suites and CI.
* Real Google / Microsoft / GitHub servers: no credentials for them may be used in tests. The same code path is
  exercised against a local OpenID Connect provider (real redirect, PKCE, userinfo) and with the
  provider's network part replaced in API tests.

## Re-test
After the fixes every automated level was run again (backend pytest, Vitest, Playwright desktop/tablet/
phone incl. axe, Storybook axe, Lighthouse, Docker smoke test). Results are in the PR checks.
