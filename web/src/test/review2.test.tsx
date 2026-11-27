import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockApi, renderApp } from "./helpers";

// 2026-11-26: the compare page is back in the menu, improved: the source page beside its distilled text, the places
// boxed on the source, and a number difference confirmed place by place (which releases a file held by the guard).
const ME = { id: "1", email: "a@example.com", role: "reviewer" };
const ROOM = { id: "r1", name: "AS 5601", threshold: 95, number_guard: true, archived: false };
const FILE = {
  rel: "/AS 5601.2-2010.pdf", name: "AS 5601.2-2010.pdf", kind: "pdf", size: 1, state: "below", accuracy: 99.4, diffs: 2,
  number_diffs: 2, numbers_open: 2, reason: null, detail: null, pages: 69,
};
const PLACES = { items: [
  { i: 0, kind: "numbers", page: 12, detail: "missing: 14, 2.75", known: false },
  { i: 1, kind: "numbers", page: 30, detail: "missing: 7", known: false },
], ai: { enabled: false, skills: {} } };
const PAGE = {
  rel: FILE.rel, page: 12, pages: 69, has_source: true, distilled: "The test pressure is 7 kPa for minutes.",
  source_text: "The test pressure is 7 kPa for 14 minutes.", pages_with_findings: [12, 30],
  items: [{ i: 0, kind: "numbers", detail: "missing: 14, 2.75", known: false,
    values: [{ value: "14", in_result: false, boxes: [[0.4, 0.2, 0.43, 0.22]] }, { value: "2.75", in_result: false, boxes: [] }] }],
};

function api(posted: unknown[]) {
  return mockApi((url, init) => {
    if (url.endsWith("/me")) return { body: ME };
    if (/\/rooms\?archived=false/.test(url)) return { body: { rooms: [ROOM] } };
    if (/\/rooms\?archived=true/.test(url)) return { body: { rooms: [] } };
    if (url.includes("/files")) return { body: { total: 1, files: [FILE] } };
    if (url.includes("/places/known")) {
      posted.push(JSON.parse(String(init?.body)));
      return { body: PLACES };
    }
    if (url.includes("/review?rel=")) return { body: PLACES };
    if (url.includes("/pages/12?rel=")) return { body: PAGE };
    return { body: {} };
  });
}

describe("compare & review page", () => {
  it("is in the main menu and opens on the first open place of the first held file", async () => {
    api([]);
    renderApp("/review?room=r1");
    expect(await screen.findByText("Source · page 12")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Compare & review" }).length).toBeGreaterThan(0);
    // why it is held, in words: the threshold is met, the number guard holds it
    expect(screen.getByText(/meets the 95% threshold; the file is held only because 2 number differences/)).toBeInTheDocument();
    // the source page picture and the box around the missing number
    const img = screen.getByAltText("Source · page 12") as HTMLImageElement;
    expect(img.src).toContain("/api/v1/rooms/r1/pages/12/image?rel=%2FAS%205601.2-2010.pdf");
    expect(document.querySelectorAll(".fx-rv-box.miss")).toHaveLength(1);
    expect(screen.getByText("The test pressure is 7 kPa for minutes.")).toBeInTheDocument();
    expect(screen.getAllByText("not in the result").length).toBe(2);
  });

  it("confirms a place as 'the source says so'", async () => {
    const posted: unknown[] = [];
    api(posted);
    renderApp(`/review?room=r1&rel=${encodeURIComponent(FILE.rel)}&page=12`);
    await userEvent.click(await screen.findByRole("button", { name: "Source says so, confirm" }));
    await waitFor(() => expect(posted).toEqual([{ rel: FILE.rel, item: 0, known: true }]));
  });
});
