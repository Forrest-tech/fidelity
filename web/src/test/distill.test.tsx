import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockApi, renderApp } from "./helpers";
import { buildTree, flatten } from "../components/RoomFiles";
import type { FileRow } from "../components/RoomFiles";

const ME = (role: string) => ({ id: "1", email: "a@example.com", role });
const counts = (o: Record<string, number> = {}) => ({
  total: 0, pending: 0, processing: 0, ok: 0, below: 0, unprocessable: 0, skipped: 0, publishing: 0, published: 0, finished: 0, rate: 0, ...o,
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

const COMPARISON = {
  rel: "/2003/a.pdf", dest: "/Transfer_Md", key: "as 3500/2003/a.pdf.md", status: "changed", accuracy: 99.5, added: 1, removed: 1, more_files: 0,
  files: [{ path: "a.pdf.md", status: "changed", added: 1, removed: 1, truncated: false,
    lines: [{ op: "@", text: "@@ -1 +1 @@" }, { op: "-", text: "Pipe size 12 mm." }, { op: "+", text: "Pipe size 15 mm." }, { op: " ", text: "Cover 30 mm." }] }],
};

function api(role: string, rooms: unknown[], extra?: (url: string, init?: RequestInit) => { body?: unknown; status?: number } | undefined) {
  return mockApi((url, init) => {
    const e = extra?.(url, init);
    if (e) return e;
    if (url.endsWith("/me")) return { body: ME(role) };
    if (url.endsWith("/cloud/ready")) return { body: { dropbox: true, google: false } };
    if (url.includes("/queue")) return { body: { capacity: 2, used: 0, running: [], queued: [] } };
    if (/\/rooms\?archived/.test(url)) return { body: { rooms } };
    if (url.includes("/accept-preview")) return { body: { ok: 1, below: 1, published: 0, publishing: 0, has_dest: true, dest: "/Transfer_Md" } };
    if (url.includes("/files")) return { body: { total: FILES.length, files: FILES } };
    if (url.includes("/accept-impact")) return { body: { new: 1, replaces: 0 } };
    if (url.includes("/folders?path=%2Fas%203500%2F2018")) return { body: { path: "/as 3500/2018", folders: [] } };
    if (url.includes("/folders?path=%2Fas%203500")) return { body: { path: "/as 3500", folders: [{ name: "2018", path: "/as 3500/2018" }] } };
    if (url.includes("/folders")) return { body: { path: "/", folders: [{ name: "as 3500", path: "/as 3500" }, { name: "Transfer_Md", path: "/Transfer_Md" }] } };
    if (url.includes("/compare")) return { body: COMPARISON };
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
    const first = (await screen.findByText("AS 3500")).closest(".fx-room") as HTMLElement;
    expect(within(first).getByText("1 to review")).toBeInTheDocument();
    expect(within(first).getByRole("img", { name: /Meets threshold 1/ })).toBeInTheDocument();          // open: the state bar of its files
    expect(await within(first).findByLabelText(/^Input/)).toBeInTheDocument();           // open: its settings are shown
    const second = screen.getByText("NCC 2025").closest(".fx-room") as HTMLElement;
    expect(within(second).queryByLabelText(/^Input/)).not.toBeInTheDocument();           // folded: only the summary
    expect(within(second).getByText("100%")).toBeInTheDocument();
    expect(within(second).getByText(/\/as 3500|No input yet/)).toBeInTheDocument();
  });

  it("opens a folded room on click", async () => {
    api("reviewer", [room(), room({ id: "r2", name: "NCC 2025" })]);
    renderApp("/distill");
    await screen.findByText("NCC 2025");
    await userEvent.setup().click(screen.getByRole("button", { name: "Open NCC 2025" }));
    const second = screen.getByText("NCC 2025").closest(".fx-room") as HTMLElement;
    expect(await within(second).findByLabelText(/^Input/)).toBeInTheDocument();
  });

  it("keeps a new room as a draft until Save, then makes it with its folders in one step", async () => {
    sessionStorage.clear();
    const calls = api("reviewer", [], (url, init) => (url.endsWith("/rooms") && init?.method === "POST" ? { body: room({ id: "r9", name: "Room 1" }) } : undefined));
    renderApp("/distill");
    expect(await screen.findByText("No rooms yet.")).toBeInTheDocument();
    const u = userEvent.setup();
    await u.click(screen.getByRole("button", { name: /New room/ }));
    const draft = await screen.findByRole("region", { name: "New room (not saved)" });
    expect(calls.some((x) => x.url.endsWith("/rooms") && x.init?.method === "POST")).toBe(false);   // nothing made yet
    const save = within(draft).getByRole("button", { name: "Save room" });
    expect(save).toBeDisabled();                                                                    // needs the input folder
    await u.type(within(draft).getByLabelText(/^Input/), "/as 3500");
    await u.type(within(draft).getByLabelText(/^Output/), "/Transfer_Md/as 3500");
    // look the button up again: the draft area may re-render while typing (the cloud check arrives), leaving `save` detached
    const saveNow = () => within(screen.getByRole("region", { name: "New room (not saved)" })).getByRole("button", { name: "Save room" });
    await waitFor(() => expect(saveNow()).toBeEnabled(), { timeout: 20_000 });
    await u.click(saveNow());
    await waitFor(() => {
      const c = calls.find((x) => x.url.endsWith("/rooms") && x.init?.method === "POST");
      expect(JSON.parse(String(c?.init?.body))).toEqual({ prefix: "Room", source: "/as 3500", dest: "/Transfer_Md/as 3500", mode: "distill" });
    });
    await waitFor(() => expect(screen.queryByRole("region", { name: "New room (not saved)" })).not.toBeInTheDocument());
    expect(sessionStorage.getItem("fidelity.draftRoom")).toBeNull();
  });

  it("takes a shared link from someone else's Dropbox as the input after checking it; the output picker has no link box", async () => {
    sessionStorage.clear();
    const LINK = "https://www.dropbox.com/scl/fo/abc/def?rlkey=k1";
    const calls = api("reviewer", [], (url) => (url.includes("/folders/link?") ? {
      body: { link: LINK, name: "Australian Standards", in_account: false, path: null, files: 165, supported: 153, size_mb: 739.7, complete: false },
    } : undefined));
    renderApp("/distill");
    expect(await screen.findByText("No rooms yet.")).toBeInTheDocument();
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(screen.getByRole("button", { name: /New room/ }));
    const draft = await screen.findByRole("region", { name: "New room (not saved)" });
    await u.click(within(draft).getByRole("button", { name: /Choose a folder for Input/ }));
    const box = await screen.findByLabelText(/Or paste a Dropbox shared link/);
    await u.type(box, LINK + "&st=x&dl=0");
    await u.click(screen.getByRole("button", { name: "Check" }));
    expect(await screen.findByText("Found: Australian Standards", {}, { timeout: 10_000 })).toBeInTheDocument();
    expect(screen.getByText(/At least 165 files, 153 of them can be distilled/)).toBeInTheDocument();
    expect(calls.some((c) => c.url.includes("/folders/link?url=" + encodeURIComponent(LINK + "&st=x&dl=0")))).toBe(true);
    await u.click(screen.getByRole("button", { name: "Use this link as the input" }));
    await waitFor(() => expect(within(screen.getByRole("region", { name: "New room (not saved)" })).getByLabelText(/^Input/)).toHaveValue(LINK));
    await u.click(within(screen.getByRole("region", { name: "New room (not saved)" })).getByRole("button", { name: /Choose a folder for Output/ }));
    await screen.findByText("Use this folder");
    expect(screen.queryByLabelText(/Or paste a Dropbox shared link/)).toBeNull();
  });

  it("says what to do with a file link, and the output picker can name a new folder", async () => {
    sessionStorage.clear();
    api("reviewer", [], (url) => (url.includes("/folders/link?") ? {
      status: 422, body: { detail: "file_link: this is a link to one file; share the folder that holds the files instead" },
    } : undefined));
    renderApp("/distill");
    expect(await screen.findByText("No rooms yet.")).toBeInTheDocument();
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(screen.getByRole("button", { name: /New room/ }));
    const draft = await screen.findByRole("region", { name: "New room (not saved)" });
    await u.click(within(draft).getByRole("button", { name: /Choose a folder for Input/ }));
    await u.type(await screen.findByLabelText(/Or paste a Dropbox shared link/), "https://www.dropbox.com/scl/fi/x/a.pdf?rlkey=r");
    await u.click(screen.getByRole("button", { name: "Check" }));
    expect(await screen.findByText(/This is a link to one file. Share the folder/, {}, { timeout: 10_000 })).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Cancel" }));
    await u.click(within(screen.getByRole("region", { name: "New room (not saved)" })).getByRole("button", { name: /Choose a folder for Output/ }));
    await u.type(await screen.findByPlaceholderText("New folder name"), "Gas library");
    await u.click(screen.getByRole("button", { name: "Use new folder" }));
    await waitFor(() => expect(within(screen.getByRole("region", { name: "New room (not saved)" })).getByLabelText(/^Output/)).toHaveValue("/Gas library"));
  });

  it("says before the room is filled in when no cloud storage is connected, and who can fix it", async () => {
    sessionStorage.clear();
    for (const [role, hint] of [["reviewer", "Ask an administrator to connect one."], ["admin", "Connect one in Settings → Cloud storage."]] as const) {
      api(role, [], (url) => (url.endsWith("/cloud/ready") ? { body: { dropbox: false, google: false } } : undefined));
      const { unmount } = renderApp("/distill");
      await userEvent.setup().click(await screen.findByRole("button", { name: /New room/ }));
      const draft = await screen.findByRole("region", { name: "New room (not saved)" });
      expect(await within(draft).findByRole("alert")).toHaveTextContent(hint);
      if (role === "admin") expect(within(draft).getByRole("link", { name: hint })).toHaveAttribute("href", "/settings/storage");
      unmount();
      sessionStorage.clear();
    }
  });

  it("discards a draft without making anything", async () => {
    sessionStorage.clear();
    const calls = api("reviewer", []);
    renderApp("/distill");
    await screen.findByText("No rooms yet.");
    const u = userEvent.setup();
    await u.click(screen.getByRole("button", { name: /New room/ }));
    const draft = await screen.findByRole("region", { name: "New room (not saved)" });
    await u.type(within(draft).getByLabelText(/^Input/), "/as 3500");
    await u.click(within(draft).getByRole("button", { name: "Discard" }));
    expect(screen.queryByRole("region", { name: "New room (not saved)" })).not.toBeInTheDocument();
    expect(calls.some((x) => x.url.endsWith("/rooms") && x.init?.method === "POST")).toBe(false);
    expect(sessionStorage.getItem("fidelity.draftRoom")).toBeNull();
  });

  it("asks before leaving the page with an unsaved draft: stay, or discard and go", async () => {
    sessionStorage.clear();
    api("reviewer", [], (url) => (url.includes("/notifications") ? { body: { items: [], unread: 0 } } : undefined));
    renderApp("/distill");
    await screen.findByText("No rooms yet.");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(screen.getByRole("button", { name: /New room/ }));
    const draft = await screen.findByRole("region", { name: "New room (not saved)" });
    await u.type(within(draft).getByLabelText(/^Input/), "/as 3500");
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    await u.click(within(nav).getByRole("link", { name: "Overview" }));
    const dlg = await screen.findByRole("dialog");
    expect(within(dlg).getByText("Leave without saving?")).toBeInTheDocument();
    await u.click(within(dlg).getByRole("button", { name: "Stay" }));
    expect(screen.getByRole("region", { name: "New room (not saved)" })).toBeInTheDocument();      // still here, still typed
    await u.click(within(nav).getByRole("link", { name: "Overview" }));
    await u.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Discard" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
  });

  it("asks before leaving with a room's folders edited, and Save there saves them", async () => {
    sessionStorage.clear();
    const calls = api("reviewer", [room()], (url) => (url.includes("/notifications") ? { body: { items: [], unread: 0 } } : undefined));
    renderApp("/distill");
    const input = await screen.findByLabelText(/^Input/);
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.clear(input);
    await u.type(input, "/as 3500/2018");
    await u.click(within(screen.getByRole("navigation", { name: "Main navigation" })).getByRole("link", { name: "Results" }));
    const dlg = await screen.findByRole("dialog");
    await u.click(within(dlg).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      const p = calls.find((x) => x.url.endsWith("/rooms/r1") && x.init?.method === "PATCH");
      expect(JSON.parse(String(p?.init?.body))).toMatchObject({ source: "/as 3500/2018" });
    });
    expect(await screen.findByRole("heading", { level: 1, name: "Results" })).toBeInTheDocument();
  });

  it("brings an unsaved draft back after a reload", async () => {
    sessionStorage.setItem("fidelity.draftRoom", JSON.stringify({ name: "Plumbing", source: "/as 3500", dest: "", mode: "distill" }));
    api("reviewer", []);
    renderApp("/distill");
    const draft = await screen.findByRole("region", { name: "New room (not saved)" });
    expect(within(draft).getByText(/unsaved new room is back/)).toBeInTheDocument();
    expect(within(draft).getByLabelText("Room name")).toHaveValue("Plumbing");
    expect(within(draft).getByLabelText(/^Input/)).toHaveValue("/as 3500");
    sessionStorage.clear();
  });

  it("shows every file a run works on, its step and how far it is, and which files wait", async () => {
    const now = Date.now() / 1000;
    const live = {
      v: 2, stage: "running", started: now - 120, updated: now, total: 6, done: 1, skipped: 1, workers: 2,
      active: {
        "/2003/a.pdf": { stage: "ocr", page: 12, pages: 40, scan: true, since: now - 60, stage_since: now - 440 },
        "/2003/amend/b.pdf": { stage: "downloading", bytes: 3_100_000, size: 9_400_000, since: now - 5 },
        "/2003/amend/c.pdf": { stage: "checking", since: now - 90 },
        "/2018/x.pdf": { stage: "ready", since: now - 1900, stage_since: now - 1900 },
      },
      queued: ["/2018/d.pdf", "/2018/e.pdf"], counts: { PASS: 1 },
    };
    api("reviewer", [room({ job: { id: "j1", status: "running", progress: 30, message: "", live } })]);
    renderApp("/distill");
    const panel = await screen.findByRole("region", { name: "Run progress" });
    expect(within(panel).getByText("Distilling")).toBeInTheDocument();
    expect(within(panel).getByText("1 of 5 done")).toBeInTheDocument();
    expect(within(panel).getByText("2 files being read at once")).toBeInTheDocument();   // OCR + checking; not the download or the waiting one
    expect(within(panel).getByText("a.pdf")).toBeInTheDocument();
    expect(within(panel).getByText("page 12 of 40 · 40 s a page, about 19 min left")).toBeInTheDocument();   // 11 pages in 440 s
    expect(within(panel).getByText("3.1 / 9.4 MB")).toBeInTheDocument();
    const steps = within(panel).getAllByRole("list", { name: "Steps of this file" });
    expect(steps[0].querySelector('[aria-current="step"]')?.textContent).toContain("OCR");
    expect(steps[1].querySelector('[aria-current="step"]')?.textContent).toContain("Download");
    expect(steps[3].querySelector("li.wait")?.textContent).toContain("Waiting to read");   // downloaded, not read yet
    expect(steps[3].querySelector('[aria-current="step"]')).toBeNull();
    expect(within(panel).getByText(/2 files waiting/)).toBeInTheDocument();
    expect(within(panel).getAllByRole("progressbar").length).toBeGreaterThanOrEqual(3);
    // the file waiting for a free reader has not started: no clock beside it (it read as half an hour spent on it)
    const waiting = within(panel).getByText("x.pdf").closest("li") as HTMLElement;
    expect(within(waiting).queryByText(/^\d+:\d\d$/)).not.toBeInTheDocument();
  });

  it("says why a file was skipped or could not be processed, and duplicates are not failures", async () => {
    const files = [
      file("/AS 3500.0 Glossary.pdf", "skipped", { reason: "duplicate", detail: "same content as /2018/AS 3500.0 Glossary.pdf", pages: null }),
      file("/2018/P.pdf", "skipped", { reason: "protected", covered_by: "/2018/P-已解锁.pdf", pages: null }),
      file("/2018/S.pdf", "unprocessable", { reason: "protected", pages: null }),
      file("/2018/P-已解锁.pdf", "ok", { accuracy: 99.9 }),
      file("/1990/N.pdf", "unprocessable", { reason: "network", pages: null }),
    ];
    api("reviewer", [room({ counts: counts({ total: 5, ok: 1, unprocessable: 2, skipped: 2, finished: 5, rate: 100 }) })],
      (url) => (url.includes("/files") ? { body: { total: files.length, files } } : undefined));
    renderApp("/distill");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByRole("radio", { name: "Flat" }));
    expect(await screen.findByText("Skipped · same as AS 3500.0 Glossary.pdf")).toHaveClass("p-idle");
    expect(screen.getByText("Skipped · same edition used: P-已解锁.pdf")).toHaveClass("p-idle");
    const prot = screen.getByText("Cannot be processed · copying text not allowed");
    expect(prot).toHaveClass("p-bad");
    // the reason in full is in the cell's tooltip
    const tipOf = async (el: HTMLElement, re: RegExp) => {
      await u.hover(el);
      await waitFor(() => expect(screen.getAllByRole("tooltip").some((t) => re.test(t.textContent || ""))).toBe(true), { timeout: 5000 });
      await u.unhover(el);
    };
    await tipOf(prot, /forbid copying its text[\s\S]*unlocked copy of it in the same folder/);
    await tipOf(screen.getByText("Cannot be processed · network dropped"), /next run tries it again/);
    // a skipped file points to the file that covers it instead of opening an empty result
    expect(screen.getByRole("button", { name: /^Show the file that covers .*P.pdf$/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Fix .*P\.pdf$/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Retry .*S\.pdf$/ })).not.toBeInTheDocument();   // retrying cannot help
    expect(screen.getByRole("button", { name: /^Retry .*N\.pdf$/ })).toBeInTheDocument();          // a dropped connection: it can
  });

  it("shows each file's edition and marks an edition a newer one replaces", async () => {
    const ed = (designation: string, status: "current" | "superseded", superseded_by = "", copy_of: string | null = null) =>
      ({ designation, amendment: null, status, superseded_by, copy_of, copies: copy_of ? 2 : 1 });
    const files = [
      file("/2015/AS 3500.1-2015.pdf", "published", { accuracy: 99.9, edition: ed("AS/NZS 3500.1:2015", "superseded", "AS/NZS 3500.1:2021") }),
      file("/2021/AS NZS 3500.1-2021.pdf", "published", { accuracy: 99.9, edition: { ...ed("AS/NZS 3500.1:2021", "current"), newer_edition: "AS/NZS 3500.1:2025" } }),
      file("/2021/SS/AS-NZS_3500.1-2021 Printed.pdf", "skipped", { accuracy: 86.2, covered_by: "/2021/AS NZS 3500.1-2021.pdf",
        edition: ed("AS/NZS 3500.1:2021", "current", "", "/2021/AS NZS 3500.1-2021.pdf") }),
      file("/notes/site.pdf", "ok", { accuracy: 99.9 }),
    ];
    api("reviewer", [room({ counts: counts({ total: 4, ok: 1, published: 2, skipped: 1, finished: 4, rate: 100 }) })],
      (url) => (url.includes("/files") ? { body: { total: files.length, files } }
        : url.includes("/editions") ? { body: { standards: 1, current: 1, superseded: 1, amendments: 0, extra_copies: 1, published_twice: 0, editions: [], code: "NCC 2025", missing: [{ designation: "AS/NZS 3500.1:2025", title: "Water services", clauses: ["B1D3"] }] } } : undefined));
    renderApp("/distill");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByRole("radio", { name: "Flat" }));
    const old = (await screen.findByText("AS/NZS 3500.1:2015")).parentElement as HTMLElement;
    expect(within(old).getByText("old")).toBeInTheDocument();
    await u.hover(old);
    expect(await screen.findByRole("tooltip")).toHaveTextContent(/Superseded by AS\/NZS 3500\.1:2021/);
    await u.unhover(old);
    expect(screen.getAllByText("AS/NZS 3500.1:2021")).toHaveLength(2);
    expect(screen.getByText("Skipped · same edition used: AS NZS 3500.1-2021.pdf")).toBeInTheDocument();
    expect(await screen.findByText(/1 standards · 1 current editions · 1 older editions · 0 amendments · 1 extra copies not published/)).toBeInTheDocument();
    expect(screen.getByText("NCC 2025 calls up 1 editions this room does not hold: AS/NZS 3500.1:2025")).toBeInTheDocument();
    expect(within(screen.getAllByText("AS/NZS 3500.1:2021")[0].parentElement as HTMLElement).getByText("newer exists")).toBeInTheDocument();
  });

  it("columns can be made wider or narrower by dragging or with the arrow keys, and every cell shows its full text on hover", async () => {
    api("reviewer", [room()]);
    localStorage.removeItem("fidelity.distill.colwidths");
    renderApp("/distill");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByRole("radio", { name: "Flat" }));
    const handle = await screen.findByRole("separator", { name: "Resize column Name" });
    expect(handle).toHaveAttribute("aria-valuenow", "340");
    // drag the right edge of the Name column 60 px to the right
    handle.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, clientX: 500, pointerId: 1 }));
    window.dispatchEvent(new PointerEvent("pointermove", { clientX: 560, pointerId: 1 }));
    window.dispatchEvent(new PointerEvent("pointerup", { clientX: 560, pointerId: 1 }));
    await waitFor(() => expect(screen.getByRole("separator", { name: "Resize column Name" })).toHaveAttribute("aria-valuenow", "400"));
    // keyboard: narrower by one step; never below the minimum
    screen.getByRole("separator", { name: "Resize column Name" }).focus();
    await u.keyboard("{ArrowLeft}");
    await waitFor(() => expect(screen.getByRole("separator", { name: "Resize column Name" })).toHaveAttribute("aria-valuenow", "384"));
    expect(JSON.parse(localStorage.getItem("fidelity.distill.colwidths") || "{}").name).toBe(384);   // remembered
    for (const col of ["Edition", "Files / pages", "State", "Progress / accuracy"]) expect(screen.getByRole("separator", { name: `Resize column ${col}` })).toBeInTheDocument();
    // hover: the full path of a file, and the full status with its reason
    const cell = (re: RegExp) => [...document.querySelectorAll<HTMLElement>(".fx-celltip")].find((el) => re.test(el.textContent || ""))!;
    await u.hover(cell(/b\.pdf$/));
    await waitFor(() => expect(screen.getAllByRole("tooltip").some((el) => (el.textContent || "").includes("/2003/amend/b.pdf"))).toBe(true), { timeout: 5000 });
    await u.unhover(cell(/b\.pdf$/));
    await u.hover(cell(/^Below threshold/));
    await waitFor(() => expect(screen.getAllByRole("tooltip").some((el) => /Below threshold/.test(el.textContent || ""))).toBe(true), { timeout: 5000 });
  });

  it("withdraws a second published copy of an edition after a confirmation", async () => {
    const ed = { designation: "AS/NZS 3500.3:2021", amendment: null, status: "current" as const, superseded_by: "", copies: 2 };
    const files = [
      file("/2021/AS NZS 3500.3-2021.pdf", "published", { accuracy: 99.8, edition: { ...ed, copy_of: null } }),
      file("/2021/SS/AS-NZS_3500.3-2021 Searchable.pdf", "published", { accuracy: 99.0, covered_by: "/2021/AS NZS 3500.3-2021.pdf",
        edition: { ...ed, copy_of: "/2021/AS NZS 3500.3-2021.pdf" } }),
    ];
    const calls = api("reviewer", [room({ counts: counts({ total: 2, published: 2, finished: 2, rate: 100 }) })],
      (url, init) => (url.includes("/withdraw") && init?.method === "POST" ? { body: { job: "j9", count: 1 } }
        : url.includes("/files") ? { body: { total: files.length, files } } : undefined));
    renderApp("/distill");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByRole("radio", { name: "Flat" }));
    expect(screen.getByText("Accepted · same edition also published: AS NZS 3500.3-2021.pdf")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Withdraw .*AS NZS 3500\.3-2021\.pdf/ })).not.toBeInTheDocument();   // the one kept
    await u.click(screen.getByRole("button", { name: /^Withdraw .*Searchable\.pdf/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/nothing is deleted/)).toBeInTheDocument();
    await u.click(within(dialog).getByRole("button", { name: "Withdraw" }));
    await waitFor(() => expect(calls.some((c) => c.url.includes("/withdraw") && String(c.init?.body).includes("Searchable.pdf"))).toBe(true));
  });

  it("explains every state and reason in one place", async () => {
    api("reviewer", [room()]);
    renderApp("/distill");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByRole("button", { name: "What do these mean?" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Below threshold")).toBeInTheDocument();
    expect(within(dialog).getByText(/compare with the source page/)).toBeInTheDocument();
    expect(within(dialog).getByText("copying text not allowed")).toBeInTheDocument();
    expect(within(dialog).getByText("Same edition used")).toBeInTheDocument();
  });

  it("an empty room that was never set up can be set up or deleted from its card", async () => {
    const calls = api("reviewer", [room(), room({ id: "r2", name: "Room 2", source: null, dest: null, counts: counts() })],
      (url, init) => (url.endsWith("/rooms/r2") && init?.method === "DELETE" ? { body: {} } : undefined));
    renderApp("/distill");
    const card = (await screen.findByText("Room 2")).closest(".fx-room") as HTMLElement;
    expect(within(card).getByText("Empty: no input folder yet")).toBeInTheDocument();
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(within(card).getByRole("button", { name: "Delete" }));
    await u.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/rooms/r2") && c.init?.method === "DELETE")).toBe(true));
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
      expect(JSON.parse(String(patch?.init?.body))).toEqual({ source: "/as 3500/2018", dest: "/Transfer_Md" });
    });
  });

  it("an interrupted run says so and offers to continue", async () => {
    api("reviewer", [room({ job: { id: "j", status: "interrupted", progress: 40, message: "x" } })]);
    renderApp("/distill");
    expect(await screen.findAllByText("Interrupted")).not.toHaveLength(0);
    expect(await screen.findByRole("button", { name: "Continue" })).toBeInTheDocument();
  });

  it("a queued room shows its place and can be moved to the front", async () => {
    const calls = api("reviewer", [room({ job: { id: "j", status: "queued", progress: 0, message: "queued", position: 2 } })], (url) =>
      url.includes("/queue")
        ? { body: { capacity: 2, used: 2, running: [{ job: "a", room: "r0", name: "NCC", points: 2 }],
            queued: [{ job: "b", room: "r9", name: "Other", position: 1, points: 1, priority: 1 }, { job: "j", room: "r1", name: "AS 3500", position: 2, points: 1, priority: 1 }] } }
        : undefined);
    renderApp("/distill");
    expect((await screen.findAllByText("Waiting, no. 2")).length).toBeGreaterThan(0);
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(screen.getByRole("button", { name: "Manage the queue and priority" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getAllByRole("button", { name: "Run next" })).toHaveLength(1);   // only the one that is not first
    await u.click(within(dialog).getByRole("button", { name: "Run next" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/rooms/r1/front") && c.init?.method === "POST")).toBe(true));
  });

  it("accepts the files that qualify after a confirmation that names the destination", async () => {
    const calls = api("reviewer", [room()]);
    renderApp("/distill");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByRole("button", { name: "Accept 1 that qualify" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/published to \/Transfer_Md/)).toBeInTheDocument();
    await waitFor(() => expect(dialog).toHaveTextContent(/New\s*1\s*Replace\s*0/));
    await u.click(within(dialog).getByRole("button", { name: "Accept" }));
    await waitFor(() => {
      const c = calls.find((x) => x.url.endsWith("/rooms/r1/accept"));
      expect(JSON.parse(String(c?.init?.body))).toEqual({ all_ok: true, checked_flagged: false });
    });
  });

  it("names the files that still have flagged places and accepts only after the person says they looked", async () => {
    const calls = api("reviewer", [room()], (url) => (url.includes("/accept-preview")
      ? { body: { ok: 1, below: 1, published: 0, publishing: 0, has_dest: true, dest: "/Transfer_Md",
          flagged: { files: 1, places: 4, examples: [{ rel: "/2003/a.pdf", places: 4 }] } } } : undefined));
    renderApp("/distill");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByRole("button", { name: "Accept 1 that qualify" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/1 of these files still have flagged places \(4 in all\)/)).toBeInTheDocument();
    expect(within(dialog).getByText("a.pdf — 4 flagged places")).toBeInTheDocument();
    const go = within(dialog).getByRole("button", { name: "Accept" });
    expect(go).toBeDisabled();
    await u.click(within(dialog).getByRole("checkbox", { name: "I have looked at the flagged places of these files" }));
    expect(go).toBeEnabled();
    await u.click(go);
    await waitFor(() => {
      const c = calls.find((x) => x.url.endsWith("/rooms/r1/accept"));
      expect(JSON.parse(String(c?.init?.body))).toEqual({ all_ok: true, checked_flagged: true });
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
    expect(await screen.findByRole("img", { name: "Capacity 2 of 2 points" })).toBeInTheDocument();
    expect(screen.getByText("Queue").parentElement).toHaveTextContent(/running\s*1\s*·\s*waiting\s*1/);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "More" }));
    await u.click(await screen.findByText("Archive"));
    expect(await screen.findByText(/cannot archive yet/)).toBeInTheDocument();
  });

  it("picks the input folder by browsing Dropbox", async () => {
    api("reviewer", [room()]);
    renderApp("/distill");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByRole("button", { name: "Choose a folder for Input (read only)" }));
    const dialog = (await screen.findByText("Use this folder")).closest(".ant-modal") as HTMLElement;
    await u.click(await within(dialog).findByText("2018"));                              // opened at the typed folder
    expect(await within(dialog).findByText("No folders inside.")).toBeInTheDocument();
    await u.click(within(dialog).getByText("Use this folder"));
    expect(await screen.findByDisplayValue("/as 3500/2018")).toBeInTheDocument();
    expect(screen.getByText("Save")).toBeInTheDocument();
  });

  it("will not save an output folder inside the input folder", async () => {
    api("reviewer", [room()]);
    renderApp("/distill");
    const u = userEvent.setup();
    const out = await screen.findByDisplayValue("/Transfer_Md");
    await u.clear(out);
    await u.type(out, "/as 3500/out");
    expect(await screen.findByText("The output folder must be outside the input folder.")).toBeInTheDocument();
    expect(screen.getByText("Save").closest("button")).toBeDisabled();
  });

  it("compares a file with the copy in the output folder, line by line", async () => {
    api("reviewer", [room()]);
    renderApp("/distill");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByLabelText("Expand 2003"));
    await u.click(await screen.findByLabelText("Compare a.pdf with the output folder"));
    expect(await screen.findByText("Compared with the output folder: 1 lines added, 1 removed.")).toBeInTheDocument();
    expect(screen.getByText("Pipe size 12 mm.")).toBeInTheDocument();
    expect(screen.getByText("Pipe size 15 mm.")).toBeInTheDocument();
  });

  it("deletes a room only after asking", async () => {
    const calls = api("reviewer", [room()]);
    renderApp("/distill");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByRole("button", { name: "More" }));
    await u.click(await screen.findByRole("menuitem", { name: "Delete" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Delete the room “AS 3500”?");
    expect(calls.some((c) => c.init?.method === "DELETE")).toBe(false);
    await u.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(calls.some((c) => c.init?.method === "DELETE")).toBe(false);
    await u.click(screen.getByRole("button", { name: "More" }));
    await u.click(await screen.findByRole("menuitem", { name: "Delete" }));
    await u.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/rooms/r1") && c.init?.method === "DELETE")).toBe(true));
  });
});
