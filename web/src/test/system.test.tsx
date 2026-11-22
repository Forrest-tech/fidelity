import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockApi, renderApp } from "./helpers";

const ME = (role: string) => ({ id: "1", email: "a@example.com", role });
const GB = 1024 ** 3;
const HEALTH = (o: Record<string, unknown> = {}) => ({
  version: "ef49158", uptime_s: 2 * 86400 + 3600, cpus: 2,
  disk: { free: 1.2 * GB, total: 50 * GB }, memory: { available: 0.9 * GB },
  runs: { days: 7, done: 10, failed: 13, interrupted: 1, total: 24, failure_rate: 0.583, queued: 0, running: 1,
    last_failure: { message: "This machine ran out of disk space for the work files.", updated_at: 1 } },
  backup: null,
  alerts: [
    { key: "disk:1", level: "bad", kind: "disk", free: 1.2 * GB },
    { key: "backup:none", level: "warn", kind: "backup_none" },
  ],
  ...o,
});

describe("system health", () => {
  it("shows what needs doing first, the figures, and makes a verified backup on request", async () => {
    let backedUp = false;
    const calls = mockApi((url, init) => {
      if (url.endsWith("/me")) return { body: ME("admin") };
      if (url.endsWith("/system/backup") && init?.method === "POST") {
        backedUp = true;
        return { body: { ok: true } };
      }
      if (url.endsWith("/system/health")) {
        return { body: backedUp ? HEALTH({ alerts: [], backup: { path: "x.zip", created: "20261122", at: Date.now() / 1000, size: 5.8e6, files: 2008, ok: true, problems: [] } }) : HEALTH() };
      }
      return { body: {} };
    });
    renderApp("/settings/system");
    const disk = await screen.findByText(/Only 1\.2 GB of disk left/);
    const status = disk.closest('[role="status"]') as HTMLElement;
    expect(within(status).getAllByText(/^(Act now|Note)$/).map((e) => e.textContent)).toEqual(["Act now", "Note"]);   // worst first
    expect(screen.getByText(/10 done · 13 failed · 1 stopped/)).toBeInTheDocument();
    expect(screen.getByText(/ran out of disk space/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: /Disk 98% used/ })).toBeInTheDocument();
    expect(screen.getByText("No backup yet.")).toBeInTheDocument();
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(screen.getByRole("button", { name: "Back up now" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/system/backup"))).toBe(true));
    expect(await screen.findByText("Restored and checked")).toBeInTheDocument();
    expect(screen.getByText("All is well.")).toBeInTheDocument();
  });

  it("is not offered to people who are not administrators", async () => {
    mockApi((url) => (url.endsWith("/me") ? { body: ME("reviewer") } : { body: {} }));
    renderApp("/settings/system");
    await waitFor(() => expect(screen.queryByText("System health")).not.toBeInTheDocument());
  });
});
