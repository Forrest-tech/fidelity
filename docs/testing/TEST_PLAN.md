# Fidelity web app: test plan

Owner: development. Applies to every page of the web app (`web/`) and the API behind it (`backend/`).
Test cases: [TEST_CASES.md](TEST_CASES.md). Findings, scores and fixes of each test round: [FINDINGS.md](FINDINGS.md).

## 1. What we test and why

Fidelity turns source documents into verified Markdown that AI tools quote. A person uses it to sign in,
set up sources and output places, start distill runs, follow their progress, read the results and fix what
the checks flagged. A defect that loses a run, publishes unverified text, lets the wrong person change
something, or leaves a person unsure what happened is serious; a cosmetic slip is not.

In scope: every page (sign-in and first-run set-up, Overview, Distill rooms, Results, Review, Sources,
Jobs, Settings and its sections, Users), the sign-in API (password, Google/Microsoft/GitHub/company SSO,
bot check, rate limits), roles (administrator, reviewer, viewer), both languages, light and dark themes,
desktop/tablet/phone sizes, and network failures.

Out of scope here: extraction accuracy of the distill pipeline (own benchmark suites in `backend/tests`
and `docs/benchmarks`), Mac-only engines, and the real Google/Microsoft/GitHub servers (their protocol is
exercised against a local OpenID Connect provider; see 4.3).

## 2. Levels and tools (all open source, all in CI)

| Level | Tool | Where | What it proves |
|---|---|---|---|
| API and rules | pytest + FastAPI TestClient | `backend/tests/` | each endpoint: real values, boundaries, bad input, roles, rate limits, audit |
| Component | Vitest + Testing Library (+ user-event) | `web/src/test/` | each page's states (loading, empty, data, error), validation, role-dependent controls |
| User flows | Playwright, real backend, real browser | `web/e2e/` | what a person does, end to end, as they would do it |
| Accessibility | axe-core in Playwright and Storybook | `web/e2e/`, `web/stories-check/` | WCAG 2.1 A/AA on every page, light and dark |
| Responsive | Playwright projects desktop 1280, tablet 768, phone 375 | `web/e2e/` | no sideways scrolling, navigation reachable, nothing cut off |
| Visual | Playwright screenshots against Linux baselines | `web/e2e/` | no unintended visual change |
| Performance and practice | Lighthouse CI | CI `frontend-build` | performance, accessibility, best practices on the sign-in page |

### How the user-flow tests simulate a real person
Playwright drives a real Chromium against the real backend and a throw-away database seeded with three
users (one per role). The tests act only through what a person perceives: they find controls by their
role and visible name (`getByRole`, `getByLabel`), type with the keyboard, click, wait for what appears on
screen, and never reach into component state or call the API to skip a step. The bot check is the real
ALTCHA widget solving a real proof-of-work in the page (made cheap for speed). Sign-in with a company
identity provider goes through the real redirect flow against a local OpenID Connect server
(oauth2-mock-server), including PKCE. Network failures are produced with Playwright's request routing
(`page.route`) so the page sees exactly what a dropped or failed request looks like.

This follows established practice: user-centric queries (Testing Library guiding principles), the
Playwright best-practice guide (test user-visible behaviour, isolate tests, use web-first assertions),
and the WCAG 2.1 AA checks of axe-core used by Deque, Microsoft and Google.

## 3. Test data

* Real data: copies of real source PDFs (AS 3500 and NCC 2025 volumes) and real published Markdown from
  the live output, copied into the test instance's own data folder. The live source folders are
  read-only by rule and are never touched by tests.
* Boundary values: empty, one character, the maximum length (e-mail 320, room name, path), just over the
  maximum, exactly at a limit (5th and 6th failed sign-in, 60th and 61st call), zero and many items.
* Bad input: wrong types, malformed e-mail, spaces only, SQL and HTML/script text, very long text,
  Chinese and other non-Latin text, paths outside the allowed folders, forged or replayed tokens.
* Network: request fails (offline), server error 500, slow response, session expired (401) mid-use.
* Both languages (English, Chinese) and both themes for every page.

Test credentials only. No real person's password or e-mail is used; e-mails are `@example.com`.

## 4. Environments

1. CI (GitHub Actions, Linux): the reliable signal. Nine checks must be green before merge.
2. Local isolated instance: the worktree build on its own port with its own data folder and database,
   used for exploratory testing in a real browser. Never the live server on port 8000 and never the live
   `web/dist`.
3. Identity providers: a local OpenID Connect provider (`web/e2e/oauth-mock.mjs`) for automated tests.
   Google, Microsoft and GitHub use the same code path (httpx-oauth clients) and are covered by API
   tests with the provider's network part replaced; they are switched on in production by setting their
   credentials (see `docs/runbook/admin.en.md`).

## 5. How a round runs

1. Run all automated levels. Record every failure.
2. Exploratory session per page, as each role, in both languages, at phone and desktop size: try the main
   task, then real data, boundaries, bad input and network failures. Record every problem, including
   pages that are confusing or do not fit how people work.
3. For each finding: research how mature products solve it, write down options, score each option 0-10
   on user value, correctness/risk, consistency with the rest of the app, effort and maintainability
   (weighted 30/25/20/15/10). Implement an option only when it scores 9.5 or more; otherwise record why
   it waits.
4. Add a test that fails without the fix. Re-run everything. A round ends when every automated check
   passes and no open finding is at or above 9.5.

## 6. Entry and exit criteria

Entry: the branch builds; backend and web unit tests pass locally.
Exit: all CI checks green; every test case in TEST_CASES.md is automated or marked manual with a
result; FINDINGS.md lists every finding with its score and outcome.

## 7. Running the tests

```
cd backend;  PYTHONUTF8=1 python -m pytest -q
cd web;      npm test                      # Vitest
cd web;      npm run build; npm run e2e    # Playwright (PYTHON=<venv python>)
cd web;      npm run build-storybook; npm run check-stories
```
