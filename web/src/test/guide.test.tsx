import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockApi, renderApp } from "./helpers";

const ME = (role: string) => ({ id: "1", email: "a@example.com", role });
const counts = (o: Record<string, number> = {}) => ({ total: 0, pending: 0, processing: 0, ok: 0, below: 0, unprocessable: 0, skipped: 0, publishing: 0, published: 0, finished: 0, rate: 0, ...o });
const room = (o: Record<string, unknown> = {}) => ({
  id: "r1", name: "AS 3500", position: 1, source: { kind: "dropbox", link: "/AS 3500" }, dest: { kind: "dropbox", link: "/Transfer_Md" },
  mode: "distill", threshold: 99, number_guard: false, priority: 1, points: 1, archived: false, job: null, counts: counts(), accuracy_avg: null, ...o,
});

function api(role: string, rooms: unknown[], cloud = { dropbox: true, google: false }) {
  return mockApi((url) => {
    if (url.endsWith("/me")) return { body: ME(role) };
    if (url.endsWith("/cloud/ready")) return { body: cloud };
    if (/\/rooms\?archived=false/.test(url)) return { body: { rooms } };
    if (/\/rooms\?archived=true/.test(url)) return { body: { rooms: [] } };
    if (url.includes("/notifications")) return { body: { items: [], unread: 0 } };
    if (url.includes("/corrections")) return { body: { rules: [], total: 0, enabled: 0 } };
    return { body: {} };
  });
}

describe("getting started", () => {
  it("ticks off what is done and offers the next step's button", async () => {
    api("admin", [room({ counts: counts({ total: 10, finished: 10, ok: 8, rate: 100 }) })]);
    renderApp("/");
    const guide = (await screen.findByRole("heading", { name: "Get started" })).closest("section") as HTMLElement;
    expect(within(guide).getByText("3 of 4 done")).toBeInTheDocument();
    const steps = within(guide).getAllByRole("listitem");
    expect(steps[3]).toHaveAttribute("aria-current", "step");
    expect(within(steps[3]).getByRole("link", { name: "Review results" })).toHaveAttribute("href", "/distill?room=r1&state=ok");
    expect(within(steps[0]).getByText(/done/)).toBeInTheDocument();
  });

  it("tells a reviewer who cannot connect storage to ask an administrator", async () => {
    api("reviewer", [], { dropbox: false, google: false });
    renderApp("/");
    const guide = (await screen.findByRole("heading", { name: "Get started" })).closest("section") as HTMLElement;
    expect(within(guide).getByText(/ask one/)).toBeInTheDocument();
    expect(within(guide).queryByRole("link", { name: "Connect" })).not.toBeInTheDocument();
  });

  it("disappears once everything is done, and can be hidden", async () => {
    api("admin", [room({ counts: counts({ total: 2, finished: 2, published: 2, rate: 100 }) })]);
    renderApp("/");
    await screen.findByText("AS 3500");
    expect(screen.queryByRole("heading", { name: "Get started" })).not.toBeInTheDocument();
  });

  it("hides when asked", async () => {
    api("admin", []);
    renderApp("/");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByRole("button", { name: "Hide this guide" }));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Get started" })).not.toBeInTheDocument());
    try { localStorage.removeItem("fidelity.gettingStarted.hidden"); } catch { /* jsdom */ }
  });
});
