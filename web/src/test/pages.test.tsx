import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
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
    await userEvent.setup({ pointerEventsCheck: 0 }).click(screen.getByRole("radio", { name: "Failed" })); // the input is visually hidden; its label takes the click
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
    expect(await screen.findByText("Cloud sync (Dropbox / Google Drive)")).toBeInTheDocument();
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
    await u.click(await screen.findByRole("tab", { name: /Finished/ }));
    expect(await screen.findByText("Source folder verified unchanged.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Roll back this run" })).not.toBeInTheDocument();
  });

  it("a running run opens by itself with live status and can be cancelled", async () => {
    const now = Date.now() / 1000;
    const RUNNING = { ...RUN, id: "r9", status: "running", progress: 40, message: "OCR page 3/10" };
    const LIVE = { ...RUNNING, log: ["[2] Scan.pdf"], summary: null,
      live: { started: now - 90, updated: now - 2, total: 5, index: 2, file: "Scan.pdf", stage: "ocr", page: 3, pages: 10,
              scan: true, counts: { PASS: 1 }, skipped: 0 } };
    const calls = api("reviewer", (url, init) => {
      if (url.endsWith("/dropbox/sync") && (!init || init.method !== "POST")) return { body: { runs: [RUNNING] } };
      if (url.endsWith("/dropbox/sync/r9/cancel")) return { body: { cancelled: true } };
      if (url.includes("/dropbox/sync/r9")) return { body: LIVE };
      return undefined;
    });
    renderApp("/sources");
    expect(await screen.findByText("Reading a scanned document (OCR)")).toBeInTheDocument();
    expect(screen.getByText("File 2 of 5")).toBeInTheDocument();
    expect(screen.getByText("OCR page 3 of 10")).toBeInTheDocument();
    expect(screen.getByText(/This file is a scan/)).toBeInTheDocument();
    const u = userEvent.setup({ pointerEventsCheck: 0 }); // skips per-click style checks, slow on this DOM
    // text queries: role queries are slow on Ant Design's large DOM
    await u.click(screen.getByText("Cancel run"));
    await u.click(await screen.findByText("OK")); // the confirmation
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/dropbox/sync/r9/cancel") && c.init?.method === "POST")).toBe(true));
  }, 60_000);

  it("warns when Dropbox access is not set up", async () => {
    api("admin", (url) => (url.endsWith("/dropbox/status") ? { body: { reader: true, writer: false } } : undefined));
    renderApp("/sources");
    expect(await screen.findByRole("alert")).toHaveTextContent("Not connected yet: Dropbox writer");
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
    await u.click(screen.getByLabelText("Email"));
    await u.paste("a@example.com");
    await u.click(screen.getByLabelText("Password"));
    await u.paste("long-enough-pw");
    await u.click(screen.getByLabelText("Confirm password"));
    await u.paste("different-pw!");
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
    renderApp("/settings/storage");
    expect(await screen.findByText("Cloud storage")).toBeInTheDocument();
    expect(await screen.findByText("Connected as Forrest (f@example.com)")).toBeInTheDocument();
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    const writer = screen.getByText("Write access (output folders)").closest("section")!;
    await u.click(within(writer).getByLabelText("Dropbox App key"));
    await u.paste("testappkey00001");
    await u.click(within(writer).getByText("Connect"));
    expect((await within(writer).findByText(/Open Dropbox/)).closest("a")).toHaveAttribute("href", "https://www.dropbox.com/oauth2/authorize?x");
    const post = calls.find((c) => c.url.endsWith("/storage/dropbox/start"));
    expect(JSON.parse(String(post?.init?.body))).toEqual({ role: "writer", app_key: "testappkey00001" });
  }, 90_000);

  it("reviewers do not see cloud storage", async () => {
    mockApi((url) => (url.endsWith("/me") ? { body: ME("reviewer") } : { body: {} }));
    renderApp("/settings");
    await screen.findByRole("heading", { name: "Settings" });
    expect(screen.queryByText("Cloud storage")).not.toBeInTheDocument();
  });
});

describe("Google Drive", () => {
  const G0 = { client_configured: false, client_id: "", redirect_uri: "http://localhost:8000/api/v1/storage/google/callback",
    reader: { connected: false, account: null }, writer: { connected: false, account: null } };

  it("shows the redirect URI and asks for the OAuth client first", async () => {
    const calls = mockApi((url, init) => {
      if (url.endsWith("/me")) return { body: ME("admin") };
      if (url.endsWith("/storage/google") && !init?.method) return { body: G0 };
      if (url.endsWith("/storage/dropbox")) return { body: { reader: { connected: false, app_key: "", account: null }, writer: { connected: false, app_key: "", account: null } } };
      return { body: {} };
    });
    renderApp("/settings/storage");
    expect(await screen.findByText("http://localhost:8000/api/v1/storage/google/callback")).toBeInTheDocument();
    const u = userEvent.setup();
    await u.click(screen.getByLabelText("OAuth client ID"));
    await u.paste("123-abc.apps.googleusercontent.com");
    await u.click(screen.getByLabelText("OAuth client secret"));
    await u.paste("fake-secret-for-tests");
    await u.click(screen.getByRole("button", { name: "Save client" }));
    const put = calls.find((c) => c.url.endsWith("/storage/google/client"));
    expect(put?.init?.method).toBe("PUT");
  });

  it("a Google Drive source needs the Google reader connection", async () => {
    mockApi((url) => {
      if (url.endsWith("/me")) return { body: ME("admin") };
      if (url.endsWith("/dropbox/status")) return { body: { reader: true, writer: true, google: { reader: false, writer: false } } };
      if (url.endsWith("/dropbox/sync")) return { body: { runs: [] } };
      return { body: SRC };
    });
    localStorage.removeItem("fidelity.dropboxLinks");
    renderApp("/sources");
    const u = userEvent.setup();
    await u.click(await screen.findByLabelText(/Source folder/));
    await u.paste("https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOp");
    await u.click(screen.getByLabelText(/Output folder/));
    await u.paste("/Transfer_Md");
    expect(await screen.findByRole("alert")).toHaveTextContent("Google Drive reader");
    expect(screen.getByRole("button", { name: "Start dry run" })).toBeDisabled();
  });
});
