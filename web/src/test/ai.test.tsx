import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockApi, renderApp } from "./helpers";

const ME = (role: string) => ({ id: "1", email: "a@example.com", role });
const ZERO = { calls: 0, cached: 0, blocked: 0, errors: 0, invalid: 0, spend: 0, adopted: 0, modified: 0, rejected: 0, adoption: null, paused_s: 0 };
const SETTINGS = (o: Record<string, unknown> = {}) => ({
  enabled: false,
  providers: [],
  skills: {
    arbitrate: { provider: null, model: null, level: 1, budget_usd: 20, monthly_cap: 500 },
    explain: { provider: null, model: null, level: 1, budget_usd: 20, monthly_cap: 500 },
  },
  scope: { allowed_prefixes: [], block_licensed: true },
  evals: {},
  kinds: { anthropic: { label: "Anthropic", models: ["claude-opus-5-5"], custom: false }, custom: { label: "Custom (OpenAI-compatible)", models: [], custom: true } },
  stats: { skills: { arbitrate: { ...ZERO, calls: 12, cached: 4, spend: 0.31, adopted: 9, rejected: 1, adoption: 90 }, explain: ZERO }, memory: { cache: 40, examples: 9, rules: 3 } },
  examples: { arbitrate: 9, explain: 0 },
  ...o,
});
const PROV = { id: "p1", kind: "anthropic", label: "Anthropic", base_url: null, models: ["claude-opus-5-5"], prices: {}, last4: "abcd" };

describe("AI settings", () => {
  it("adds a provider without ever showing the key, and shows how each skill is doing", async () => {
    const calls = mockApi((url, init) => {
      if (url.endsWith("/me")) return { body: ME("admin") };
      if (url.endsWith("/ai/providers") && init?.method === "POST") return { body: SETTINGS({ providers: [PROV] }) };
      if (url.endsWith("/ai/settings")) return { body: SETTINGS() };
      return { body: {} };
    });
    renderApp("/settings/ai");
    expect(await screen.findByRole("switch", { name: "Use AI" })).toHaveAttribute("aria-checked", "false");
    expect(screen.getByText("AI calls this month").nextElementSibling).toHaveTextContent("12");
    expect(screen.getByText("$0.31")).toBeInTheDocument();
    expect(screen.getByText("90%")).toBeInTheDocument(); // taken by people
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(screen.getByRole("button", { name: "+ Add" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Add a provider");
    await u.type(within(dialog).getByLabelText("API key"), "sk-ant-secret-key-abcd");
    expect(within(dialog).getByLabelText("API key")).toHaveAttribute("type", "password");
    await u.click(within(dialog).getByRole("button", { name: "Add" }));
    expect(await screen.findByText(/key ••••abcd/)).toBeInTheDocument();
    expect(screen.queryByText(/sk-ant-secret/)).not.toBeInTheDocument();
    const post = calls.find((c) => c.url.endsWith("/ai/providers"));
    expect(JSON.parse(String(post?.init?.body))).toEqual({ kind: "anthropic", key: "sk-ant-secret-key-abcd", base_url: null });
  });

  it("will not add a key that is too short", async () => {
    mockApi((url) => (url.endsWith("/me") ? { body: ME("admin") } : url.endsWith("/ai/settings") ? { body: SETTINGS() } : { body: {} }));
    renderApp("/settings/ai");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByRole("button", { name: "+ Add" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Add a provider");
    await u.type(within(dialog).getByLabelText("API key"), "short");
    expect(within(dialog).getByRole("button", { name: "Add" })).toBeDisabled();
  });

  it("switches AI on and saves a skill's level", async () => {
    const calls = mockApi((url, init) => {
      if (url.endsWith("/me")) return { body: ME("admin") };
      if (url.endsWith("/ai/settings")) return { body: SETTINGS({ providers: [PROV], enabled: init?.method === "PUT" }) };
      return { body: {} };
    });
    renderApp("/settings/ai");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByRole("switch", { name: "Use AI" }));
    await waitFor(() => expect(calls.some((c) => c.init?.method === "PUT" && JSON.parse(String(c.init.body)).enabled === true)).toBe(true));
    await u.click(screen.getAllByRole("button", { name: /^Edit / })[0]);
    const dialog = await screen.findByRole("dialog");
    await u.click(within(dialog).getByRole("radio", { name: "By default" }));
    await u.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      const put = calls.filter((c) => c.init?.method === "PUT").pop();
      expect(JSON.parse(String(put?.init?.body)).skills.arbitrate.level).toBe(2);
    });
  });

  it("is not shown to people who may not change it", async () => {
    mockApi((url) => (url.endsWith("/me") ? { body: ME("reviewer") } : { body: {} }));
    renderApp("/settings/ai");
    expect(await screen.findByRole("heading", { level: 1, name: "Account" })).toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: "Use AI" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "AI" })).not.toBeInTheDocument();
  });
});

// ------------------------------------------------------------------ the places in the Fix panel
const counts = { total: 1, pending: 0, processing: 0, ok: 0, below: 1, unprocessable: 0, skipped: 0, publishing: 0, published: 0, finished: 1, rate: 100 };
const ROOM = { id: "r1", name: "Scans", source: { kind: "dropbox", link: "/as 3500" }, dest: null, mode: "distill", threshold: 99, number_guard: true,
  priority: 1, points: 2, archived: false, updated_at: 1, counts, job: null };
const FILE = { rel: "/scan.pdf", name: "scan.pdf", kind: "pdf", size: 1, state: "below", accuracy: 96.0, diffs: 2, number_diffs: 0, reason: null, detail: null, pages: 3 };
const PLACE = { i: 0, kind: "reading", page: 2, detail: "fittcd / fitted", candidates: ["fittcd", "fitted"], in_text: "fittcd", before: "Each pipe shall be", after: "to the wall" };

function fileApi(suggestion: unknown, level = 1) {
  return mockApi((url, init) => {
    if (url.endsWith("/me")) return { body: ME("reviewer") };
    if (url.includes("/queue")) return { body: { capacity: 2, used: 0, running: [], queued: [] } };
    if (/\/rooms\?archived/.test(url)) return { body: { rooms: [ROOM] } };
    if (url.includes("/accept-preview")) return { body: { ok: 0, below: 1, published: 0, publishing: 0, has_dest: false, dest: null } };
    if (url.includes("/files")) return { body: { total: 1, files: [FILE] } };
    if (url.includes("/result?rel=")) return { body: { rel: FILE.rel, series: null, files: [{ path: "scan.pdf.md", text: "Each pipe shall be fittcd to the wall", cut: false }], corrections: [] } };
    if (url.includes("/review?rel=")) return { body: { items: [{ ...PLACE, suggestion }, { i: 1, kind: "numbers", page: 3, detail: "missing: 20", suggestion: null }], ai: { enabled: true, skills: { arbitrate: { level }, explain: { level } } } } };
    if (url.endsWith("/corrections/preview")) return { body: { kind: "text", before: "", after: "", series: null, here: 1, others: [], other_places: 0 } };
    if (url.endsWith("/corrections") && init?.method === "POST") return { body: { rule: { id: "k1", num: 1 }, others: [] } };
    return { body: {} };
  });
}

describe("uncertain places", () => {
  it("lists them, opens the first one and takes its other reading as the final text", async () => {
    fileApi(null);
    renderApp("/distill");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByRole("button", { name: "Review scan.pdf" }));
    const side = await screen.findByRole("complementary", { name: "The chosen place" });
    expect(screen.getByText("missing: 20")).toBeInTheDocument();
    expect(within(side).getByLabelText("Correct text")).toHaveValue("fitted");
    await u.click(within(side).getByRole("button", { name: "fittcd" }));
    expect(within(side).getByLabelText("Correct text")).toHaveValue("fittcd");
  });

  it("asks the AI, and a fix made from its suggestion records that the person took it", async () => {
    const calls = fileApi({ call: "c1", skill: "arbitrate", status: "ok", message: "", decision: null,
      result: { text: "fitted", choice: 1, confidence: 0.93, reason: "a real word here", needs_human: false } });
    renderApp("/distill");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByRole("button", { name: "Review scan.pdf" }));
    expect(await screen.findByText(/a real word here/)).toBeInTheDocument();
    await u.click(screen.getByRole("row", { name: "numbers 3" }));                     // the numbers place
    await u.click(await screen.findByRole("button", { name: "Explain" }));
    await waitFor(() => expect(JSON.parse(String(calls.find((c) => c.url.endsWith("/rooms/r1/ask"))?.init?.body))).toEqual({ rel: "/scan.pdf", item: 1 }));
    await u.click(screen.getByRole("row", { name: "reading 2" }));
    const save = await screen.findByRole("button", { name: "Confirm and save" });
    await waitFor(() => expect(save).toBeEnabled(), { timeout: 3000 });            // after the preview
    await u.click(save);
    await waitFor(() => {
      const d = calls.find((c) => c.url.endsWith("/ai/calls/c1/decision"));
      expect(JSON.parse(String(d?.init?.body))).toEqual({ decision: "adopted", final: "fitted" });
    });
  });

  it("at level 2 asks about new places when the file is opened", async () => {
    const calls = fileApi(null, 2);
    renderApp("/distill");
    await userEvent.setup({ pointerEventsCheck: 0 }).click(await screen.findByRole("button", { name: "Review scan.pdf" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/rooms/r1/ask-default"))).toBe(true));
  });
});
