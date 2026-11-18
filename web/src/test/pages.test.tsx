import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import en from "../locales/en.json";
import zh from "../locales/zh.json";
import { mockApi, renderApp } from "./helpers";

const ME = (role: string) => ({ id: "1", email: "a@example.com", role });
const SRC = [{ id: "n2", name: "N2 library", src_root: "C:/lib", md_root: "C:/md" }];

function keys(o: unknown, p = ""): string[] {
  return Object.entries(o as Record<string, unknown>).flatMap(([k, v]) =>
    v && typeof v === "object" ? keys(v, p + k + ".") : [p + k],
  );
}

describe("translations", () => {
  it("English and Chinese define exactly the same keys", () => {
    expect(keys(zh).sort()).toEqual(keys(en).sort());
  });
  it("no translation is empty", () => {
    for (const v of [...Object.values(flat(en)), ...Object.values(flat(zh))]) expect(v.trim()).not.toBe("");
  });
});

function flat(o: unknown, p = ""): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(o as Record<string, unknown>)) {
    if (v && typeof v === "object") Object.assign(out, flat(v, p + k + "."));
    else out[p + k] = String(v);
  }
  return out;
}

describe("overview", () => {
  it("shows counts and what needs attention", async () => {
    mockApi((url) =>
      url.endsWith("/me")
        ? { body: ME("viewer") }
        : {
            body: {
              sources: 2,
              jobs: { running: 1, queued: 2 },
              documents: { PASS: 4, FAIL: 1 },
              needs_attention: [{ rel: "b.pdf", sid: "n2", verdict: "FAIL", instruction_like: 0 }],
            },
          },
    );
    renderApp("/");
    expect(await screen.findByTestId("stat-Verified")).toHaveTextContent("4");
    expect(screen.getByTestId("stat-In progress")).toHaveTextContent("3");
    expect(screen.getByText("b.pdf")).toBeInTheDocument();
  });

  it("empty state when nothing exists", async () => {
    mockApi((url) =>
      url.endsWith("/me") ? { body: ME("viewer") } : { body: { sources: 0, jobs: {}, documents: {}, needs_attention: [] } },
    );
    renderApp("/");
    expect(await screen.findByTestId("empty-state")).toHaveTextContent("No documents have been distilled yet");
  });
});

describe("jobs and documents", () => {
  it("lists jobs with status", async () => {
    mockApi((url) =>
      url.endsWith("/me")
        ? { body: ME("viewer") }
        : { body: [{ id: "j1", kind: "distill:n2", rel: "a.pdf", status: "running", progress: 40, message: "x", created_at: 1, updated_at: 1 }] },
    );
    renderApp("/jobs");
    const row = (await screen.findByText("a.pdf")).closest("tr")!;
    expect(within(row).getByText("Running")).toBeInTheDocument();
    expect(within(row).getByText("40%")).toBeInTheDocument();
  });

  it("jobs empty state", async () => {
    mockApi((url) => (url.endsWith("/me") ? { body: ME("viewer") } : { body: [] }));
    renderApp("/jobs");
    expect(await screen.findByTestId("empty-state")).toHaveTextContent("No jobs have run yet");
  });

  it("documents: shows results and filters by verdict via the API", async () => {
    const calls = mockApi((url) =>
      url.endsWith("/me")
        ? { body: ME("viewer") }
        : { body: [{ sid: "n2", rel: "a.pdf", verdict: "FAIL", files: 3, pages: 9, checks: { tables: false, chars: true } }] },
    );
    renderApp("/documents");
    expect(await screen.findByText("a.pdf")).toBeInTheDocument();
    expect(screen.getByText(/tables/)).toBeInTheDocument();
    await userEvent.setup().selectOptions(screen.getByLabelText("Show"), "FAIL");
    await screen.findByText("a.pdf");
    expect(calls.some((c) => c.url.includes("verdict=FAIL"))).toBe(true);
  });
});

describe("sources actions follow the role", () => {
  it("viewer sees no action buttons", async () => {
    mockApi((url) => (url.endsWith("/me") ? { body: ME("viewer") } : { body: SRC }));
    renderApp("/sources");
    await screen.findByText("N2 library");
    expect(screen.queryByRole("button", { name: "Distill all PDFs" })).not.toBeInTheDocument();
  });

  it("reviewer can start a batch and sees the confirmation", async () => {
    const calls = mockApi((url) => {
      if (url.endsWith("/me")) return { body: ME("reviewer") };
      if (url.endsWith("/distill/batch")) return { body: { jobs: ["a", "b"], files: 2 } };
      return { body: SRC };
    });
    renderApp("/sources");
    await userEvent.setup().click(await screen.findByRole("button", { name: "Distill all PDFs" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Started 2 job(s).");
    expect(calls.some((c) => c.url.endsWith("/distill/batch") && c.init?.method === "POST")).toBe(true);
  });

  it("shows the server's message when the batch request is refused", async () => {
    mockApi((url) => {
      if (url.endsWith("/me")) return { body: ME("reviewer") };
      if (url.endsWith("/distill/batch")) return { status: 404, body: { detail: "source or folder not found" } };
      return { body: SRC };
    });
    renderApp("/sources");
    await userEvent.setup().click(await screen.findByRole("button", { name: "Distill all PDFs" }));
    expect(await screen.findByRole("status")).toHaveTextContent("source or folder not found");
  });
});

describe("users (admin)", () => {
  it("lists users and creates one", async () => {
    let created = false;
    const calls = mockApi((url, init) => {
      if (url.endsWith("/me")) return { body: ME("admin") };
      if (url.endsWith("/users/register")) {
        created = true;
        return { status: 201, body: {} };
      }
      if (url.endsWith("/admin/users"))
        return { body: [{ id: "1", email: "a@example.com", role: "admin", is_active: true }, ...(created ? [{ id: "2", email: "new@example.com", role: "viewer", is_active: true }] : [])] };
      return { body: [] };
    });
    renderApp("/users");
    const user = userEvent.setup();
    expect(await screen.findByText("a@example.com", { selector: "td" })).toBeInTheDocument();
    await user.type(screen.getByRole("form", { name: "Add a user" }).querySelector("input[type=email]") as HTMLElement, "new@example.com");
    await user.type(screen.getByRole("form", { name: "Add a user" }).querySelector("input[type=password]") as HTMLElement, "long-enough-password");
    await user.click(screen.getByRole("button", { name: "Create user" }));
    expect(await screen.findByText("new@example.com")).toBeInTheDocument();
    const call = calls.find((c) => c.url.endsWith("/users/register"))!;
    expect(JSON.parse(String(call.init?.body))).toMatchObject({ email: "new@example.com", role: "viewer" });
  });
});
