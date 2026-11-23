import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockApi, renderApp } from "./helpers";
import i18n from "../locales";

const ME = (role: string) => ({ id: "1", email: "a@example.com", role });
const ZERO = { calls: 0, cached: 0, blocked: 0, errors: 0, invalid: 0, spend: 0, adopted: 0, modified: 0, rejected: 0, adoption: null, paused_s: 0 };
const SKILL = (level = 2) => ({ provider: "p1", model: "claude-opus-5-5", level, budget_usd: 20, monthly_cap: 500 });
const SETTINGS = (o: Record<string, unknown> = {}) => ({
  enabled: true,
  providers: [{ id: "p1", kind: "anthropic", label: "Anthropic", base_url: null, models: ["claude-opus-5-5"], prices: {}, last4: "abcd" }],
  skills: { arbitrate: SKILL(2), explain: SKILL(1), transcribe: SKILL(1), suggest: SKILL(1) },
  scope: { allowed_prefixes: ["/as 3500"], block_licensed: true },
  evals: {},
  kinds: { anthropic: { label: "Anthropic", models: ["claude-opus-5-5"], custom: false } },
  stats: { skills: { arbitrate: ZERO, explain: ZERO, transcribe: ZERO, suggest: ZERO }, memory: { cache: 0, examples: 0, rules: 0 } },
  examples: { arbitrate: 0, explain: 0, transcribe: 0, suggest: 0 },
  level3: { eligible: false, decided: 120, adoption: 96.5, auto: { total: 0, right: 0, wrong: 0 }, pending: 0,
    missing: [{ code: "decided", have: 120, need: 300 }, { code: "adoption", have: 96.5, need: 98 }] },
  demotions: [],
  ...o,
});

describe("automatic adoption in the AI settings", () => {
  it("cannot be chosen until it is earned, and says what is missing", async () => {
    mockApi((url) => (url.endsWith("/me") ? { body: ME("admin") } : url.endsWith("/ai/settings") ? { body: SETTINGS() } : { body: {} }));
    renderApp("/settings/ai");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByRole("button", { name: "Edit Reading arbitration" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Automatic adoption is not earned yet: 120 of 300 suggestions decided by people · people took 96.5% \(needs 98%\)/)).toBeInTheDocument();
    expect(within(dialog).getByRole("radio", { name: "Automatic (text only)" })).toBeDisabled();
    expect(within(dialog).getByRole("radio", { name: "By default" })).toBeEnabled();
  });

  it("can be switched on once earned, and shows when it fell back by itself", async () => {
    const calls = mockApi((url, init) => {
      if (url.endsWith("/me")) return { body: ME("admin") };
      if (url.endsWith("/ai/settings"))
        return { body: SETTINGS({ level3: { eligible: true, decided: 320, adoption: 98.8, missing: [], auto: { total: 4, right: 3, wrong: 1 }, pending: 0 },
          demotions: [{ at: 1763600000, from: 3, to: 2, reason: "wang found an automatic adoption wrong in a.pdf (#4)" }], method: init?.method }) };
      return { body: {} };
    });
    renderApp("/settings/ai");
    // the fall-back is shown on the page itself, not only inside the skill's dialog
    expect(await screen.findByText(/Went back from level 3 to 2 by itself/)).toBeInTheDocument();
    expect(screen.getByText("wang found an automatic adoption wrong in a.pdf (#4)")).toBeInTheDocument();
    expect(screen.getByText("Suggests by default")).toBeInTheDocument();
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(screen.getByRole("button", { name: "Edit Reading arbitration" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Automatic adoption is earned/)).toBeInTheDocument();
    await u.click(within(dialog).getByRole("radio", { name: "Automatic (text only)" }));
    await u.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      const put = calls.filter((c) => c.init?.method === "PUT").pop();
      expect(JSON.parse(String(put?.init?.body)).skills.arbitrate.level).toBe(3);
    });
  });
  it("says why it fell back in the reader's language", async () => {
    mockApi((url) => {
      if (url.endsWith("/me")) return { body: ME("admin") };
      if (url.endsWith("/ai/settings"))
        return { body: SETTINGS({ demotions: [{ at: 1763600000, from: 3, to: 2, reason: "wang found an automatic adoption wrong in a.pdf (#4)",
          code: "found_wrong", args: { who: "wang", file: "a.pdf", num: "4" } }] }) };
      return { body: {} };
    });
    await i18n.changeLanguage("zh");
    try {
      renderApp("/settings/ai");
      expect(await screen.findByText("wang 抽查发现 a.pdf 里的自动采用有错（规则 #4）。")).toBeInTheDocument();
      expect(screen.queryByText(/found an automatic adoption wrong/)).not.toBeInTheDocument();
    } finally {
      await i18n.changeLanguage("en");
    }
  });
});

const PENDING = { rule: "k4", num: 4, find: "fittcd", replace: "fitted", room: "Scans", rel: "/a/scan.pdf", at: 1, before: "Each pipe is", after: "to the wall" };

describe("checking automatic adoptions", () => {
  it("lists the ones picked for a check and sends the answer", async () => {
    const calls = mockApi((url, init) => {
      if (url.endsWith("/me")) return { body: ME("reviewer") };
      if (url.endsWith("/ai/auto-checks") && !init?.method) return { body: { pending: [PENDING], total: 5, right: 2, wrong: 0 } };
      if (url.endsWith("/ai/auto-checks/k4")) return { body: { pending: [], total: 5, right: 2, wrong: 1 } };
      if (url.endsWith("/corrections/suggestions")) return { body: { suggestions: [] } };
      if (url.endsWith("/corrections")) return { body: { rules: [], total: 0, enabled: 0, disabled: 0, often_undone: 0 } };
      return { body: {} };
    });
    renderApp("/corrections");
    expect(await screen.findByText("Adopted automatically — please check")).toBeInTheDocument();
    expect(screen.getByText("fittcd")).toBeInTheDocument();
    expect(screen.getByText("Rule #4")).toBeInTheDocument();
    expect(screen.getByText(/Scans · scan\.pdf/)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Wrong" }));
    await waitFor(() => expect(JSON.parse(String(calls.find((c) => c.url.endsWith("/ai/auto-checks/k4"))?.init?.body))).toEqual({ right: false }));
    expect(await screen.findByText("Nothing waiting for a check.")).toBeInTheDocument();
  });

  it("is not shown before anything was adopted automatically", async () => {
    mockApi((url) => {
      if (url.endsWith("/me")) return { body: ME("reviewer") };
      if (url.endsWith("/ai/auto-checks")) return { body: { pending: [], total: 0, right: 0, wrong: 0 } };
      if (url.endsWith("/corrections/suggestions")) return { body: { suggestions: [] } };
      if (url.endsWith("/corrections")) return { body: { rules: [], total: 0, enabled: 0, disabled: 0, often_undone: 0 } };
      return { body: {} };
    });
    renderApp("/corrections");
    await screen.findByText("No rules yet.");
    expect(screen.queryByText("Adopted automatically — please check")).not.toBeInTheDocument();
  });
});

describe("the Fix panel", () => {
  it("marks fixes the AI adopted on its own", async () => {
    const counts = { total: 1, pending: 0, processing: 0, ok: 1, below: 0, unprocessable: 0, skipped: 0, publishing: 0, published: 0, finished: 1, rate: 100 };
    const room = { id: "r1", name: "Scans", source: { kind: "dropbox", link: "/as 3500" }, dest: null, mode: "distill", threshold: 99,
      number_guard: true, priority: 1, points: 1, archived: false, updated_at: 1, counts, job: null };
    const file = { rel: "/scan.pdf", name: "scan.pdf", kind: "pdf", size: 1, state: "ok", accuracy: 99.5, diffs: 0, number_diffs: 0,
      reason: null, detail: null, pages: 2, corrected: 1, checks: 0 };
    mockApi((url) => {
      if (url.endsWith("/me")) return { body: ME("reviewer") };
      if (url.includes("/queue")) return { body: { capacity: 2, used: 0, running: [], queued: [] } };
      if (/\/rooms\?archived/.test(url)) return { body: { rooms: [room] } };
      if (url.includes("/files")) return { body: { total: 1, files: [file] } };
      if (url.includes("/result?rel=")) return { body: { rel: "/scan.pdf", series: null, files: [{ path: "a.md", text: "fitted", cut: false }],
        corrections: [{ rule: "k4", num: 4, find: "fittcd", replace: "fitted", kind: "text", count: 1, check: false, auto: true }] } };
      return { body: {} };
    });
    renderApp("/distill");
    await userEvent.setup({ pointerEventsCheck: 0 }).click(await screen.findByRole("button", { name: "Fix scan.pdf" }));
    // in the list of fixes and in the detail of the chosen one
    expect((await screen.findAllByText("Rule #4 · adopted by AI")).length).toBeGreaterThanOrEqual(1);
  });
});
