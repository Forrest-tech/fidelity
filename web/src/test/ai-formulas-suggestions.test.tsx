import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockApi, renderApp } from "./helpers";

const ME = (role: string) => ({ id: "1", email: "a@example.com", role });
const counts = { total: 1, pending: 0, processing: 0, ok: 0, below: 1, unprocessable: 0, publishing: 0, published: 0, finished: 1, rate: 100 };
const ROOM = { id: "r1", name: "Plumbing", source: { kind: "dropbox", link: "/as 3500" }, dest: null, mode: "distill", threshold: 99, number_guard: true,
  priority: 1, points: 1, archived: false, updated_at: 1, counts, job: null };
const FILE = { rel: "/AS 3500.1.pdf", name: "AS 3500.1.pdf", kind: "pdf", size: 1, state: "below", accuracy: 97.0, diffs: 1, number_diffs: 0, reason: null, detail: null, pages: 9 };
const FORMULA = (suggestion: unknown, approved: string | null = null) => ({
  i: 0, kind: "formula", page: 4, detail: "text layer cannot be decoded",
  formulas: [{ k: 1, approved, suggestion }],
});

function fileApi(place: unknown, role = "reviewer") {
  return mockApi((url) => {
    if (url.endsWith("/me")) return { body: ME(role) };
    if (url.includes("/queue")) return { body: { capacity: 2, used: 0, running: [], queued: [] } };
    if (/\/rooms\?archived/.test(url)) return { body: { rooms: [ROOM] } };
    if (url.includes("/accept-preview")) return { body: { ok: 0, below: 1, published: 0, publishing: 0, has_dest: false, dest: null } };
    if (url.includes("/files")) return { body: { total: 1, files: [FILE] } };
    if (url.includes("/result?rel=")) return { body: { rel: FILE.rel, series: "AS 3500.1", files: [{ path: "a.md", text: "x", cut: false }], corrections: [] } };
    if (url.includes("/review?rel=")) return { body: { items: [place], ai: { enabled: true, skills: { arbitrate: { level: 1 }, explain: { level: 1 }, transcribe: { level: 1 }, suggest: { level: 1 } } } } };
    return { body: {} };
  });
}

describe("formulas", () => {
  it("shows the source image, takes the AI transcription into the box and approves it", async () => {
    const calls = fileApi(FORMULA({ call: "c7", status: "ok", message: "", decision: null,
      result: { latex: "C_p = 0.0133 I_{10}", plain: "", confidence: 0.9, unsure: false, numbers_checked: true } }));
    renderApp("/distill");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByLabelText("Fix AS 3500.1.pdf"));
    const img = await screen.findByAltText("Formula 1 on page 4 of the source");
    expect(img.getAttribute("src")).toBe("/api/v1/rooms/r1/formula.png?rel=%2FAS%203500.1.pdf&page=4&k=1");
    expect(screen.getByText("numbers found in the image")).toBeInTheDocument();
    const box = screen.getByLabelText("LaTeX of formula 1");
    expect(box).toHaveValue("C_p = 0.0133 I_{10}");
    await u.click(screen.getByText("Approve"));
    await waitFor(() => {
      const c = calls.find((x) => x.url.endsWith("/rooms/r1/formula/approve"));
      expect(JSON.parse(String(c?.init?.body))).toEqual({ rel: FILE.rel, page: 4, k: 1, latex: "C_p = 0.0133 I_{10}", call: "c7" });
    });
  });

  it("asks the AI to transcribe a formula", async () => {
    const calls = fileApi(FORMULA(null));
    renderApp("/distill");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByLabelText("Fix AS 3500.1.pdf"));
    await u.click(await screen.findByText("Transcribe"));
    await waitFor(() => expect(JSON.parse(String(calls.find((c) => c.url.endsWith("/rooms/r1/ask"))?.init?.body))).toEqual({ rel: FILE.rel, item: 0, k: 1 }));
  });

  it("a viewer sees an approved formula but cannot change it", async () => {
    fileApi(FORMULA(null, "x = 2"), "viewer");
    renderApp("/distill");
    await userEvent.setup({ pointerEventsCheck: 0 }).click(await screen.findByLabelText("Fix AS 3500.1.pdf"));
    expect(await screen.findByText("x = 2")).toBeInTheDocument();
    expect(screen.queryByText("Approve")).not.toBeInTheDocument();
  });
});

const SUG = {
  id: "s1", kind: "pattern", rule_ids: ["a", "b", "c"],
  data: { find: "\\b(\\w+t)cd\\b", replace: "\\1ed", scope: "all", series: null, nums: [2, 5, 8], counterexamples: ["cd", "card"],
    reason: "c read as e", accuracy: 100, signature: "c>e" },
  preview: { documents: 2, places: 3, samples: [{ rel: "/d.pdf", room: "One", before: "Each valve is", old: "insertcd", new: "inserted", after: "and" }] },
};

function libApi(extra?: (url: string, init?: RequestInit) => { body?: unknown } | undefined) {
  return mockApi((url, init) => {
    const e = extra?.(url, init);
    if (e) return e;
    if (url.endsWith("/me")) return { body: ME("reviewer") };
    if (url.endsWith("/corrections/suggestions")) return { body: { suggestions: [SUG] } };
    if (url.endsWith("/corrections")) return { body: { rules: [], total: 0, enabled: 0, disabled: 0, often_undone: 0 } };
    return { body: {} };
  });
}

describe("rule suggestions", () => {
  it("shows a suggested pattern with its preview and approves it", async () => {
    const calls = libApi((url) =>
      url.endsWith("/s1/approve")
        ? { body: { rule: { id: "k9", num: 9, enabled: true }, affected: [{ room_id: "r1", room: "One", rel: "/d.pdf", places: 1 }] } }
        : undefined);
    renderApp("/corrections");
    expect(await screen.findByText("Rules #2, #5, #8 fix the same kind of misread (c>e).")).toBeInTheDocument();
    expect(screen.getByText("It would change 3 more places in 2 documents.")).toBeInTheDocument();
    expect(screen.getByText("insertcd")).toBeInTheDocument();
    expect(screen.getByText(/right on 100% of the known cases · leaves cd, card alone/)).toBeInTheDocument();
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(screen.getByText("Approve"));
    expect(await screen.findByText("It now applies to 1 document. Apply it there now?")).toBeInTheDocument();
    await u.click(screen.getByText("Update 1 document"));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/corrections/k9/apply"))).toBe(true));
  });

  it("looks for suggestions and says when AI is needed", async () => {
    const calls = libApi((url) =>
      url.endsWith("/suggestions/scan") ? { body: { found: { widen: 0, pattern: 0, pattern_needs_ai: 2, pattern_rejected: 0 }, suggestions: [] } } : undefined);
    renderApp("/corrections");
    await userEvent.setup().click(await screen.findByText("Look for suggestions"));
    expect(await screen.findByText(/2 groups of similar fixes could become patterns if AI is switched on/)).toBeInTheDocument();
    expect(calls.some((c) => c.url.endsWith("/suggestions/scan") && c.init?.method === "POST")).toBe(true);
  });

  it("dismisses a suggestion", async () => {
    const calls = libApi();
    renderApp("/corrections");
    await userEvent.setup().click(await screen.findByText("Dismiss"));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/suggestions/s1/dismiss"))).toBe(true));
  });
});
