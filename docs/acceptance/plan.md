# Acceptance test plan — draft for the owner's agreement

Status: **draft v1 (2026-11-18)**. Covers spec Q-2 (answer accuracy), Q-3 (token cost), F-25 (error
reports) and the Phase 5 human trial. Phase 5 is done when the owner accepts against the specification.

> **中文摘要**：用同一套题库测试 AI 工具（先 Grok）。题库扩充到 100 题，覆盖六类难题。合格标准：
> 正确率 ≥ 99%，陷阱题（内容不可读、不存在、草案、错误前提）零容忍。题目和标准答案需要你确认。
> 每题记录答案、引用、状态和诚实度，以及耗时和调用次数。另外请两到三位员工试用一周。

## 1. What is tested

The whole chain staff will use: **published library → adapter pack → AI tool → answer with citation**.
The AI tool is Grok with the regenerated `au-compliance-kb` pack (`adapters/dist/grok/`); Claude, Codex
and Gemini packs are spot-checked with 10 questions each.

## 2. Question bank

File: `question_bank.json` (score sheet: `scoresheet.csv`). Version 1 holds the **30 questions** from the
Phase 0 Grok test. For a 99 % threshold to mean anything, the agreed bank has **100 questions**:

| Category | v1 | Target | What it checks |
|---|---|---|---|
| A Direct look-up (clause number given) | 8 | 15 | value, units, clause, page |
| B Topic, no clause number | 6 | 20 | finding the right chapter from a plain question |
| C Cross-chapter / multi-hop | 4 | 15 | definitions + clause, two Parts, cross-references |
| G State variations | (in C) | 15 | "replaces" vs "adds", correct Schedule, state named |
| D Draft vs published | 4 | 10 | draft never cited as in force |
| E Number fidelity | 4 | 10 | tables, ranges, FRLs, exact figures |
| F Traps (unreadable, missing, false premise, ambiguous) | 4 | 15 | no invented answer, ever |

Rules for questions: standard industry English, as staff would ask; every expected answer and citation
is checked against the **source PDF page**, not the Markdown. Once chat logs exist, real staff questions
replace invented ones (spec open question 2). Confirmed wrong-answer reports (`regression.json`) are added
to the bank permanently.

**Owner to provide or approve**: the 70 extra questions (I can draft them from the library for you to
check, or staff can supply real ones).

## 3. Scoring (per question)

| Field | Pass when |
|---|---|
| answer_ok | value / statement matches; numbers and units exact |
| citation_ok | document + clause + page (±1 page inside the clause's range) |
| status_ok | drafts labelled "not in force"; pending-review content labelled |
| honesty_ok | says so when content is missing or unreadable; never invents |

A question passes when all four pass. Partial answers count as fail.

## 4. Acceptance criteria

1. **≥ 99 %** of the 100 questions pass (at most 1 failure).
2. **Every F (trap) question passes** — zero tolerance (spec Q-2).
3. **Cost** (Q-3): median ≤ 4 tool calls and one file read per question; record seconds and calls in the
   score sheet. Baseline layout measurement: `docs/benchmarks/token-cost.md`.
4. **Layout decision** (assumption 4): run 20 B/C questions against the current layout and against a
   variant with small Parts merged into ~10k-token files; keep the cheaper one if accuracy is equal.
5. **Error reports work** (F-25): one deliberately disputed answer produces a report in
   `<logs>/_error_reports/` that `scripts/collect_error_reports.py` picks up.

## 5. Human trial

Two or three staff use the tool for real questions for one week (after the bank passes):
- they ask in their own words (Chinese or English), and report any doubtful answer by telling the AI
  "this is wrong" (the pack records it);
- the maintainer collects reports weekly and confirms or rejects each;
- the trial passes when no confirmed error remains unfixed and staff need no instructions beyond the
  one-page user manual.

## 6. Procedure

1. Install the regenerated pack in Grok (see `docs/runbook/admin.en.md`, "Adapter packs").
2. New chat per question; prefix nothing (the pack carries the rules).
3. Fill one row of `scoresheet.csv` per question; keep the chat link in `notes`.
4. Failures: classify (library content / pack wording / AI tool behaviour); fix the cause, regenerate,
   and re-run **the whole bank**, not only the failed question.

## 7. Decisions needed from the owner

1. Agree the categories and targets in section 2 (or change them).
2. Who writes the 70 extra questions: drafted by Claude from the library for your check, or real staff questions.
3. Which staff join the human trial, and when.
