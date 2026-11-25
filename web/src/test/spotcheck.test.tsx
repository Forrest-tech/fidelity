import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockApi, renderApp } from "./helpers";

const ME = (role: string) => ({ id: "1", email: "r@example.com", role });
const item = (n: number, verdict: string | null = null) => ({
  id: 100 + n, n, week: "2026-W48", lib_path: `/library_installation/md_library/as 3500/doc/file ${n} p4-5.md`, page: 4,
  text: `Library text of page ${n}: at least 100 mm.`, document: "AS 3500.3", source: "as 3500/2003/AS 3500.3.pdf",
  verdict, note: null, by_user: null,
});
const WEEK = (items = [item(1), item(2)], summary: Record<string, unknown> = {}) => ({
  week: "2026-W48", current: "2026-W48", items,
  summary: { weeks: [], checked: 0, wrong: 0, target: 0.01, error_upper95: null, meets_target: false, clean_pages_needed: 380, ...summary },
});

describe("weekly spot check (H-3)", () => {
  it("shows the source page beside the library text and records a verdict", async () => {
    const calls = mockApi((url, init) => {
      if (url.endsWith("/me")) return { body: ME("reviewer") };
      if (url.endsWith("/spot-check/101") && init?.method === "POST") return { body: item(1, "ok") };
      if (url.includes("/spot-check")) return { body: WEEK() };
      return { body: {} };
    });
    renderApp("/settings/spot");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByRole("button", { name: "file 1 p4-5.md" }, { timeout: 10_000 }));
    expect(await screen.findByAltText("Original PDF page 4")).toHaveAttribute("src", "/api/v1/spot-check/101/page.png");
    expect(screen.getByText(/Library text of page 1/)).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: /Matches/ }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/spot-check/101") && c.init?.method === "POST")).toBe(true));
    const body = JSON.parse(String(calls.find((c) => c.url.endsWith("/spot-check/101"))!.init!.body));
    expect(body).toEqual({ verdict: "ok", note: "" });
  });

  it("a wrong page cannot be recorded without saying what is wrong", async () => {
    mockApi((url) => {
      if (url.endsWith("/me")) return { body: ME("reviewer") };
      if (url.includes("/spot-check")) return { body: WEEK() };
      return { body: {} };
    });
    renderApp("/settings/spot");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(await screen.findByRole("button", { name: "file 2 p4-5.md" }, { timeout: 10_000 }));
    await u.click(await screen.findByRole("button", { name: "Wrong…" }));
    const save = screen.getByRole("button", { name: /Record the error/ });
    expect(save).toBeDisabled();
    await u.type(screen.getByPlaceholderText(/Table 5.3/), "150 mm on the page");
    expect(save).toBeEnabled();
  });

  it("says how many clean pages the statistics still need, and a viewer cannot give verdicts", async () => {
    mockApi((url) => {
      if (url.endsWith("/me")) return { body: ME("viewer") };
      if (url.includes("/spot-check")) return { body: WEEK([item(1, "ok")], { checked: 20, error_upper95: 0.161, clean_pages_needed: 360 }) };
      return { body: {} };
    });
    renderApp("/settings/spot");
    expect(await screen.findByText(/360 more clean pages/, {}, { timeout: 10_000 })).toBeInTheDocument();
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(screen.getByRole("button", { name: "file 1 p4-5.md" }));
    expect(await screen.findByAltText("Original PDF page 4")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Matches/ })).toBeNull();
  });
});
