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

describe("Dropbox sync on the sources page", () => {
  const LINK_A = "https://www.dropbox.com/scl/fo/a/src?rlkey=1";
  const LINK_B = "https://www.dropbox.com/scl/fo/b/out?rlkey=2";
  const RUN = {
    id: "r1", status: "done", progress: 100, message: "published", created_at: 1795000000,
    params: { source_link: LINK_A, dest_link: LINK_B, dry_run: false },
  };
  const DETAIL = {
    ...RUN, log: ["[1] a.pdf", "  verification: PASS  files=1"],
    summary: { exit_code: 0, published_run: "20261119-101500",
      report: { documents: [{ source: "a.pdf", verdict: "PASS" }, { source: "b.pdf", verdict: "FAIL" }], unchanged: ["c.pdf"], source_unchanged: true } },
  };
  const api = (role: string, extra: (url: string, init?: RequestInit) => { status?: number; body?: unknown } | undefined = () => undefined) =>
    mockApi((url, init) => {
      const e = extra(url, init);
      if (e) return e;
      if (url.endsWith("/me")) return { body: ME(role) };
      if (url.endsWith("/dropbox/status")) return { body: { reader: true, writer: true } };
      if (url.endsWith("/dropbox/sync") && (!init || init.method !== "POST")) return { body: { runs: [RUN] } };
      if (url.includes("/dropbox/sync/r1")) return { body: DETAIL };
      return { body: SRC };
    });

  it("viewer sees the runs but no form", async () => {
    api("viewer");
    renderApp("/sources");
    expect(await screen.findByText("Dropbox sync")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start dry run" })).not.toBeInTheDocument();
    expect(await screen.findByText("Finished")).toBeInTheDocument();
  });

  it("reviewer starts a dry run by default with both links", async () => {
    const calls = api("reviewer", (url, init) =>
      url.endsWith("/dropbox/sync") && init?.method === "POST" ? { body: { job: "r2", command: "-m app.distill.sync" } } : undefined);
    localStorage.removeItem("fidelity.dropboxLinks");
    renderApp("/sources");
    const u = userEvent.setup();
    await u.click(await screen.findByLabelText(/Source folder/));
    await u.paste(LINK_A);
    await u.click(screen.getByLabelText(/Output folder/));
    await u.paste(LINK_B);
    await u.click(screen.getByRole("button", { name: "Start dry run" }));
    const post = calls.find((c) => c.url.endsWith("/dropbox/sync") && c.init?.method === "POST");
    expect(JSON.parse(String(post?.init?.body))).toMatchObject({ source_link: LINK_A, dest_link: LINK_B, dry_run: true });
  });

  it("a finished run shows its counts; only admins see rollback", async () => {
    api("reviewer");
    renderApp("/sources");
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: /Finished/ }));
    expect(await screen.findByText("Source folder verified unchanged.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Roll back this run" })).not.toBeInTheDocument();
  });

  it("warns when Dropbox access is not set up", async () => {
    api("admin", (url) => (url.endsWith("/dropbox/status") ? { body: { reader: true, writer: false } } : undefined));
    renderApp("/sources");
    expect(await screen.findByRole("alert")).toHaveTextContent("missing: writer");
    expect(screen.getByRole("button", { name: "Start dry run" })).toBeDisabled();
  });
});

describe("first-run setup and cloud storage", () => {
  it("offers to create the first administrator when there are no users", async () => {
    const calls = mockApi((url, init) => {
      if (url.endsWith("/me")) return { status: 401, body: { detail: "Unauthorized" } };
      if (url.endsWith("/setup") && !init?.method) return { body: { needs_setup: true } };
      if (url.endsWith("/setup")) return { status: 201, body: { created: "a@example.com", role: "admin" } };
      return { status: 204 };
    });
    renderApp("/login");
    expect(await screen.findByText("Create the first administrator")).toBeInTheDocument();
    const u = userEvent.setup();
    await u.type(screen.getByLabelText("Email"), "a@example.com");
    await u.type(screen.getByLabelText("Password"), "long-enough-pw");
    await u.type(screen.getByLabelText("Confirm password"), "different-pw!");
    await u.click(screen.getByRole("button", { name: "Create administrator and sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("do not match");
    expect(calls.some((c) => c.url.endsWith("/setup") && c.init?.method === "POST")).toBe(false);
  });

  it("only administrators see cloud storage; connecting shows the Dropbox link", async () => {
    const calls = mockApi((url, init) => {
      if (url.endsWith("/me")) return { body: ME("admin") };
      if (url.endsWith("/storage/dropbox/start")) return { body: { url: "https://www.dropbox.com/oauth2/authorize?x", expires_in: 600 } };
      if (url.endsWith("/storage/dropbox") && !init?.method)
        return { body: { reader: { connected: true, app_key: "k1", account: { name: "Forrest", email: "f@example.com" } },
                         writer: { connected: false, app_key: "", account: null } } };
      return { body: {} };
    });
    renderApp("/settings");
    expect(await screen.findByText("Cloud storage")).toBeInTheDocument();
    expect(await screen.findByText("Connected as Forrest (f@example.com)")).toBeInTheDocument();
    const u = userEvent.setup();
    const writer = screen.getByRole("region", { name: "Write access (output folders)" });
    await u.click(within(writer).getByLabelText("Dropbox App key"));
    await u.paste("abcdEFGH1234567");
    await u.click(within(writer).getByRole("button", { name: "Connect" }));
    expect(await within(writer).findByRole("link", { name: /Open Dropbox/ })).toHaveAttribute("href", "https://www.dropbox.com/oauth2/authorize?x");
    const post = calls.find((c) => c.url.endsWith("/storage/dropbox/start"));
    expect(JSON.parse(String(post?.init?.body))).toEqual({ role: "writer", app_key: "abcdEFGH1234567" });
  });

  it("reviewers do not see cloud storage", async () => {
    mockApi((url) => (url.endsWith("/me") ? { body: ME("reviewer") } : { body: {} }));
    renderApp("/settings");
    await screen.findByRole("heading", { name: "Settings" });
    expect(screen.queryByText("Cloud storage")).not.toBeInTheDocument();
  });
});
