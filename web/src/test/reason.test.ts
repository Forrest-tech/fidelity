import { describe, expect, it } from "vitest";
import { reason } from "../components/FixDrawer";

const t = (k: string, o?: Record<string, unknown>) => `${k}|${JSON.stringify(o ?? {})}`;

describe("checker reasons in the person's language", () => {
  it("turns the checker's English into keys with their figures, and leaves anything else as it is", () => {
    expect(reason(t, "missing: 2, 0, 5")).toBe('pages.distill.reason.missing|{"nums":"2, 0, 5"}');
    expect(reason(t, "recall 0.9866, 11 characters missing")).toBe('pages.distill.reason.lost|{"n":"11","pct":"98.7"}');
    expect(reason(t, "94 characters not on the source page")).toBe('pages.distill.reason.extra|{"n":"94"}');
    expect(reason(t, "2.6.8 Gaskets")).toBe("2.6.8 Gaskets");
    expect(reason(t, null)).toBe("");
  });
});
