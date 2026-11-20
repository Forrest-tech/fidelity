import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockApi, renderApp } from "./helpers";
import { buildTree, flatten } from "../components/RoomFiles";
import type { FileRow } from "../components/RoomFiles";

const ME = (role: string) => ({ id: "1", email: "a@example.com", role });
const counts = (o: Record<string, number> = {}) => ({
  total: 0, pending: 0, processing: 0, ok: 0, below: 0, unprocessable: 0, publishing: 0, published: 0, finished: 0, rate: 0, ...o,
});
const room = (o: Record<string, unknown> = {}) => ({
  id: "r1", name: "AS 3500", source: { kind: "dropbox", link: "/as 3500" }, dest: { kind: "dropbox", link: "/Transfer_Md" },
  mode: "distill", threshold: 99, number_guard: true, priority: 1, points: 1, archived: false, updated_at: 1,
  counts: counts({ total: 4, ok: 1, below: 1, unprocessable: 1, pending: 1, finished: 3, rate: 75 }), job: null, ...o,
});
const file = (rel: string, state: string, o: Partial<FileRow> = {}): FileRow => ({
  rel, name: rel.split("/").pop()!, kind: "pdf", size: 1, state: state as FileRow["state"], accuracy: null, diffs: 0, number_diffs: 0,
  reason: null, detail: null, pages: 10, ...o,
});
const FILES = [
  file("/2003/a.pdf", "ok", { accuracy: 99.5 }),
  file("/2003/amend/b.pdf", "below", { accuracy: 97.2, diffs: 3 }),
  file("/2003/amend/c.pdf", "unprocessable", { reason: "download" }),
  file("/2018/d.pdf", "pending"),
];

function api(role: string, rooms: unknown[], extra?: (url: string, init?: RequestInit) => { body?: unknown; status?: number } | undefined) {
  return mockApi((url, init) => {
    const e = extra?.(url, init);
    if (e) return e;
    if (url.endsWith("/me")) return { body: ME(role) };
    if (url.includes("/queue")) return { body: { capacity: 2, used: 0, running: [], queued: [] } };
    if (/\/rooms\?archived/.test(url)) return { body: { rooms } };
    if (url.includes("/accept-preview")) return { body: { ok: 1, below: 1, published: 0, publishing: 0, has_dest: true, dest: "/Transfer_Md" } };
    if (url.includes("/files")) return { body: { total: FILES.length, files: FILES } };
    return { body: {} };
  });
}

describe("folder tree", () => {
  it("mirrors the source folders and rolls the states up", () => {
    const root = buildTree(FILES);
    expect(root.kids!.map((k) => k.name)).toEqual(["2003", "2018"]);
    const y2003 = root.kids![0];
    expect(y2003.counts).toMatchObject({ total: 3, ok: 1, below: 1, unprocessable: 1 });
    expect(y2003.kids!.map((k) => k.name)).toEqual(["amend", "a.pdf"]);          // folders first
    expect(root.counts!.total).toBe(4);
  });

  it("lists only what is open", () => {
    const root = buildTree(FILES);
    expect(flatten(root, new Set()).map((n) => n.name)).toEqual(["2003", "2018"]);
    expect(flatten(root, new Set(["/2003"])).map((n) => n.name)).toEqual(["2003", "amend", "a.pdf", "2018"]);
    expect(flatten(root, new Set(["/2003", "/2003/amend"])).map((n) => n.name)).toContain("b.pdf");
  });
});

describe("distill page", () => {
  it("shows a room's status, file total, finished count and rate, and opens the first room", async () => {
    api("reviewer", [room(), room({ id: "r2", name: "NCC 2025", counts: counts({ total: 5, ok: 5, finished: 5, rate: 100 }) })]);
    renderApp("/distill");
    expect(await screen.findByRole("heading", { name: "Distill" })).toBeInTheDocument();
    const first = (await screen.findByText("AS 3500")).closest(".ant-card") as HTMLElement;
    expect(within(first).getByText("1 to review")).toBeInTheDocument();
    expect(within(first).getByText("75%")).toBeInTheDocument();
    expect(await within(first).findByLabelText(/^Input/)).toBeInTheDocument();           // open: its settings are shown
    const second = screen.getByText("NCC 2025").closest(".ant-card") as HTMLElement;
    expect(within(second).queryByLabelText(/^Input/)).not.toBeInTheDocument();           // folded: only the summary
    expect(within(second).getByText("100%")).toBeInTheDocument();
    expect(within(second).getByText(/\/as 3500|No input yet/)).toBeInTheDocument();
  });

  it("opens a folded room on click", async () => {
    api("reviewer", [room(), room({ id: "r2", name: "NCC 2025" })]);
    renderApp("/distill");
    await screen.findByText("NCC 2025");
    await userEvent.setup().click(screen.getByRole("button", { name: "Open NCC 2025" }));
    const second = screen.getByText("NCC 2025").closest(".ant-card") as HTMLElement;
    expect(await within(second).findByLabelText(/^Input/)).toBeInTheDocument();
  });

  it("creates a room", async () => {
    const calls = api("reviewer", []);
    renderApp("/distill");
    expect(await screen.findByText("No rooms yet.")).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: /New room/ }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/rooms") && c.init?.method === "POST")).toBe(true));
  });

  it("a viewer can look but not change", async () => {
    api("viewer", [room()]);
    renderApp("/distill");
    await screen.findByText("AS 3500");
    expect(screen.queryByText(/New room/)).not.toBeInTheDocument();      // text queries: role queries are slow on this DOM
    expect(screen.queryByText("Start")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Rename")).not.toBeInTheDocument();
  });

  it("starts a run and sends the settings that were changed", async () => {
    const calls = api("reviewer", [room()]);
    renderApp("/distill");
    const u = userEvent.setup();
    const input = await screen.findByLabelText(/^Input/);
    await u.clear(input);
    await u.type(input, "/as 3500/2018");
    await u.click(await screen.findByRole("button", { name: "Save" }));
    await waitFor(() => {
      const patch = calls.find((c) => c.init?.method === "PATCH");
      expect(JSON.parse(String(patch?.init?.body))).toMatchObject({ source: "/as 3500/2018", threshold: 99 });
    });
  });

  it("an interrupted run says so and offers to continue", async () => {
    api("reviewer", [room({ job: { id: "j", status: "interrupted", progress: 40, message: "x" } })]);
    renderApp("/distill");
    expect(await screen.findAllByText("Interrupted")).not.toHaveLength(0);
    expect(await screen.findByRole("button", { name: "Continue" })).toBeInTheDocument();
  });

  it("a queued room shows its place and can be moved to the front", async () => {
    const calls = api("reviewer", [room({ job: { id: "j", status: "queued", progress: 0, message: "queued", position: 2 } })]);
    renderApp("/distill");
    expect(await screen.findByText("Waiting, no. 2")).toBeInTheDocument();
    await userEvent.setup().click(await screen.findByRole("button", { name: "Run next" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/rooms/r1/front") && c.init?.method === "POST")).toBe(true));
  });

  it("accepts the files that qualify after a confirmation that names the destination", async () => {
    const calls = api("reviewer", [room()]);
    renderApp("/distill");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByText("Accept 1 that qualify"));
    expect(await screen.findByText(/sent to \/Transfer_Md/)).toBeInTheDocument();
    await u.click(screen.getByText("Accept", { selector: ".ant-popover button span" }));
    await waitFor(() => {
      const c = calls.find((x) => x.url.endsWith("/rooms/r1/accept"));
      expect(JSON.parse(String(c?.init?.body))).toEqual({ all_ok: true });
    });
  });

  it("shows the queue and why a run cannot be archived", async () => {
    api("reviewer", [room()], (url, init) =>
      url.includes("/queue")
        ? { body: { capacity: 2, used: 2, running: [{ job: "a", name: "AS 3500", points: 2 }], queued: [{ job: "b", name: "NCC", position: 1, points: 1 }] } }
        : init?.method === "POST" && url.endsWith("/archive")
          ? { status: 409, body: { detail: "cannot archive yet: 1 file(s) below the threshold" } }
          : undefined);
    renderApp("/distill");
    expect(await screen.findByText("Capacity 2 of 2 points")).toBeInTheDocument();
    expect(screen.getByText("1 waiting")).toBeInTheDocument();
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "More" }));
    await u.click(await screen.findByText("Archive"));
    expect(await screen.findByText(/cannot archive yet/)).toBeInTheDocument();
  });
});
