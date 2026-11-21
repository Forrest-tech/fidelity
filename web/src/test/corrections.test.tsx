import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockApi, renderApp } from "./helpers";

const ME = (role: string) => ({ id: "1", email: "a@example.com", role });
const counts = { total: 1, pending: 0, processing: 0, ok: 1, below: 0, unprocessable: 0, skipped: 0, publishing: 0, published: 0, finished: 1, rate: 100 };
const ROOM = {
  id: "r1", name: "AS 3500", source: { kind: "dropbox", link: "/as 3500" }, dest: null, mode: "distill", threshold: 99, number_guard: true,
  priority: 1, points: 1, archived: false, updated_at: 1, counts, job: null,
};
const FILE = { rel: "/AS 3500.1-2003.pdf", name: "AS 3500.1-2003.pdf", kind: "pdf", size: 1, state: "ok", accuracy: 99.5, diffs: 0, number_diffs: 0,
  reason: null, detail: null, pages: 3, corrected: 2, checks: 0 };
const RESULT = {
  rel: FILE.rel, series: "AS 3500.1",
  files: [{ path: "AS 3500.1-2003.pdf.md", text: "---\ndocument: x\n---\n\nWatre pressure.\n", cut: false }],
  corrections: [{ rule: "k1", num: 1, find: "l50", replace: "150", kind: "number", count: 2, check: false }],
};
const RULE = (o: Record<string, unknown> = {}) => ({
  id: "k1", num: 1, find: "Watre", replace: "Water", before: "", after: "", kind: "text", scope: "series", series: "AS 3500.1", doc: null,
  enabled: true, reverts: 0, hits: 5, documents: 2, often_undone: false, source_name: "as 3500.1-2003.pdf", created_by: "wang", created_at: 1700000000, ...o,
});

function api(role: string, extra?: (url: string, init?: RequestInit) => { body?: unknown; status?: number } | undefined) {
  return mockApi((url, init) => {
    const e = extra?.(url, init);
    if (e) return e;
    if (url.endsWith("/me")) return { body: ME(role) };
    if (url.includes("/queue")) return { body: { capacity: 2, used: 0, running: [], queued: [] } };
    if (/\/rooms\?archived/.test(url)) return { body: { rooms: [ROOM] } };
    if (url.includes("/accept-preview")) return { body: { ok: 1, below: 0, published: 0, publishing: 0, has_dest: false, dest: null } };
    if (url.includes("/files")) return { body: { total: 1, files: [FILE] } };
    if (url.includes("/result?rel=")) return { body: RESULT };
    if (url.endsWith("/corrections/preview"))
      return { body: { kind: "text", before: "", after: "", series: "AS 3500.1", here: 1, others: [{ room_id: "r2", room: "Other", rel: "/AS 3500.1-2015.pdf", places: 2 }], other_places: 2 } };
    if (url.endsWith("/corrections") && init?.method === "POST") return { body: { rule: { id: "k9", num: 9 }, others: [{ room_id: "r2", room: "Other", rel: "/AS 3500.1-2015.pdf", places: 2 }] } };
    if (url.endsWith("/apply")) return { body: { documents: 1, changed: 1 } };
    if (url.endsWith("/corrections")) return { body: { rules: [RULE(), RULE({ id: "k2", num: 2, find: "l50", replace: "150", kind: "number", before: "diameter ", after: " mm", reverts: 4, often_undone: true, enabled: false })], total: 2, enabled: 1, disabled: 1, often_undone: 1 } };
    return { body: {} };
  });
}

describe("fixing a file", () => {
  it("previews a fix, saves it as a rule and applies it to the other documents", async () => {
    const calls = api("reviewer");
    renderApp("/distill");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    expect(await screen.findByText("2 auto-fixed")).toBeInTheDocument();                  // in the file list
    await u.click(screen.getByLabelText("Fix AS 3500.1-2003.pdf"));
    const side = await screen.findByRole("complementary", { name: "The chosen place" });
    expect(await within(side).findByText("Rule #1")).toBeInTheDocument();                  // the rule applied here opens first
    await u.click(screen.getByRole("button", { name: "+ Fix a misread" }));
    expect(await screen.findByText(/Watre pressure/)).toBeInTheDocument();                // the whole text shows
    await u.type(within(side).getByLabelText("Wrong text"), "Watre");
    await u.type(within(side).getByLabelText("Correct text"), "Water");
    expect(await screen.findByText(/Appears once here\./)).toBeInTheDocument();          // the preview follows the typing
    expect(screen.getByText(/2 more places in 1 other documents\./)).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Confirm and save" }));
    await waitFor(() => {
      const c = calls.find((x) => x.url.endsWith("/corrections") && x.init?.method === "POST");
      expect(JSON.parse(String(c?.init?.body))).toEqual({ room_id: "r1", rel: FILE.rel, find: "Watre", replace: "Water", scope: "series" });
    });
    expect(await screen.findByText(/Saved as rule #9/)).toBeInTheDocument();
    await u.click(screen.getByText("Fix them too (1)"));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/corrections/k9/apply"))).toBe(true));
  });

  it("will not save until there is a change", async () => {
    api("reviewer");
    renderApp("/distill");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByLabelText("Fix AS 3500.1-2003.pdf"));
    await u.click(await screen.findByRole("button", { name: "+ Fix a misread" }));
    const side = screen.getByRole("complementary", { name: "The chosen place" });
    expect(within(side).getByRole("button", { name: "Confirm and save" })).toBeDisabled();
    await u.type(within(side).getByLabelText("Wrong text"), "same");
    await u.type(within(side).getByLabelText("Correct text"), "same");
    expect(within(side).getByRole("button", { name: "Confirm and save" })).toBeDisabled();
  });

  it("undoes a rule in this document", async () => {
    const calls = api("reviewer");
    renderApp("/distill");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByLabelText("Fix AS 3500.1-2003.pdf"));
    await u.click(await screen.findByText("Undo here"));
    await waitFor(() => {
      const c = calls.find((x) => x.url.endsWith("/rooms/r1/corrections/undo"));
      expect(JSON.parse(String(c?.init?.body))).toEqual({ rel: FILE.rel, rule_id: "k1" });
    });
  });

  it("a viewer sees the result and its fixes but cannot change them", async () => {
    api("viewer");
    renderApp("/distill");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByLabelText("Fix AS 3500.1-2003.pdf"));
    expect((await screen.findAllByText("Rule #1")).length).toBeGreaterThan(0);
    await u.click(screen.getByRole("button", { name: "Show the whole result" }));
    expect(await screen.findByText(/Watre pressure/)).toBeInTheDocument();
    expect(screen.queryByText("Undo here")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "+ Fix a misread" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Wrong text")).not.toBeInTheDocument();
  });
});

describe("a file below the threshold with no flagged place", () => {
  it("says why and can be accepted on its own after a confirmation", async () => {
    const below = { ...FILE, state: "below", accuracy: 98.4, corrected: 0 };
    const calls = api("reviewer", (url) =>
      url.includes("/files") ? { body: { total: 1, files: [below] } }
        : url.includes("/result?rel=") ? { body: { ...RESULT, corrections: [] } }
        : url.includes("/review?rel=") ? { body: { items: [], ai: { enabled: false, skills: {} } } }
        : undefined);
    renderApp("/distill");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByRole("button", { name: "Review AS 3500.1-2003.pdf" }));
    expect(await screen.findByText(/Accuracy 98.4% is below the accept threshold of 99%/)).toBeInTheDocument();
    expect(screen.queryByText("Nothing in this file needs a look.")).not.toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "It is right: accept this file" }));
    expect(calls.some((c) => c.url.endsWith("/rooms/r1/accept"))).toBe(false);                 // asks first
    await u.click(await screen.findByRole("button", { name: "Accept" }));
    await waitFor(() => {
      const c = calls.find((x) => x.url.endsWith("/rooms/r1/accept"));
      expect(JSON.parse(String(c?.init?.body))).toEqual({ rels: [FILE.rel], force: true });
    });
  });
});

describe("correction library", () => {
  it("lists the rules with their use and filters those often undone", async () => {
    api("reviewer");
    renderApp("/corrections");
    expect(await screen.findByRole("heading", { name: "Correction library" })).toBeInTheDocument();
    expect(await screen.findByText("Watre")).toBeInTheDocument();
    expect(screen.getAllByText("AS 3500.1 series", { selector: "td" })).toHaveLength(2);
    expect(screen.getAllByText("in 2 documents")).toHaveLength(2);
    await userEvent.setup().click(screen.getByText("Often undone 1"));
    expect(screen.queryByText("Watre")).not.toBeInTheDocument();
    expect(screen.getByText("l50", { selector: "td code" })).toBeInTheDocument();
  });

  it("switching a rule off offers to update the documents that have it", async () => {
    const calls = api("reviewer", (url, init) =>
      init?.method === "PATCH" ? { body: { rule: RULE({ enabled: false }), affected: [{ room_id: "r1", room: "AS 3500", rel: "/AS 3500.1-2003.pdf", places: 0 }] } } : undefined);
    renderApp("/corrections");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByLabelText("Rule #1 on"));
    expect(await screen.findByText("1 document still has this fix. Take it out now?")).toBeInTheDocument();
    await u.click(screen.getByText("Update 1 document"));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/corrections/k1/apply"))).toBe(true));
    expect(JSON.parse(String(calls.find((c) => c.init?.method === "PATCH")?.init?.body))).toEqual({ enabled: false });
  });

  it("says how to make the first rule", async () => {
    api("reviewer", (url) => (url.endsWith("/corrections") ? { body: { rules: [], total: 0, enabled: 0, disabled: 0, often_undone: 0 } } : undefined));
    renderApp("/corrections");
    expect(await screen.findByText("No rules yet.")).toBeInTheDocument();
  });
});
