import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockApi, renderApp } from "./helpers";

const OPTS = (o: Record<string, unknown> = {}) => ({ providers: [], captcha: false, signup: true, ...o });
const signedOut = (extra?: (url: string, init?: RequestInit) => { body?: unknown; status?: number } | undefined, opts = OPTS()) =>
  mockApi((url, init) => {
    const e = extra?.(url, init);
    if (e) return e;
    if (url.endsWith("/me")) return { status: 401, body: { detail: "Unauthorized" } };
    if (url.endsWith("/setup")) return { body: { needs_setup: false } };
    if (url.endsWith("/auth/options")) return { body: opts };
    return { body: {} };
  });

describe("sign-in and sign-up", () => {
  it("shows the familiar I'm-not-a-robot box and asks for it before sending anything", async () => {
    const calls = signedOut(undefined, OPTS({ captcha: true }));
    renderApp("/login");
    const box = await screen.findByRole("checkbox", { name: "I'm not a robot" });
    expect(box).toHaveAttribute("aria-checked", "false");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.type(screen.getByLabelText("Email"), "a@example.com");
    await u.type(screen.getByLabelText("Password"), "correct-horse-battery");
    await u.click(screen.getByRole("button", { name: /^Sign in$/ }));
    expect(await screen.findByText("Tick “I'm not a robot” first.")).toBeInTheDocument();
    await waitFor(() => expect(box).toHaveFocus());
    expect(calls.some((c) => c.url.endsWith("/auth/login"))).toBe(false);
  });

  it("offers a clear way to create an account from the sign-in page", async () => {
    signedOut();
    renderApp("/login");
    const link = await screen.findByRole("link", { name: "Create an account" });
    expect(link).toHaveAttribute("href", "/signup");
  });

  it("sends a sign-up request and says an administrator will approve it", async () => {
    const calls = signedOut((url, init) => (url.endsWith("/auth/signup") && init?.method === "POST" ? { status: 201, body: { status: "pending" } } : undefined));
    renderApp("/signup");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.type(await screen.findByLabelText("Email"), " New@Example.com ");
    await u.type(screen.getByLabelText("Password"), "a-new-long-password");
    await u.type(screen.getByLabelText("Confirm password"), "a-new-long-password");
    await u.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText("Request sent")).toBeInTheDocument();
    const sent = calls.find((c) => c.url.endsWith("/auth/signup"));
    expect(JSON.parse(String(sent!.init!.body))).toMatchObject({ email: "New@Example.com", password: "a-new-long-password" });
  });

  it("catches a short or mismatched password before sending", async () => {
    const calls = signedOut();
    renderApp("/signup");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.type(await screen.findByLabelText("Email"), "x@example.com");
    await u.type(screen.getByLabelText("Password"), "short");
    await u.type(screen.getByLabelText("Confirm password"), "other");
    await u.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText(/at least 10/)).toBeInTheDocument();
    expect(calls.some((c) => c.url.endsWith("/auth/signup"))).toBe(false);
  });

  it("tells a person whose account waits for approval why they cannot sign in yet", async () => {
    signedOut((url) => (url.endsWith("/auth/login") ? { status: 403, body: { detail: "ACCOUNT_PENDING" } } : undefined));
    renderApp("/login");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.type(await screen.findByLabelText("Email"), "new@example.com");
    await u.type(screen.getByLabelText("Password"), "a-new-long-password");
    await u.click(screen.getByRole("button", { name: /^Sign in$/ }));
    expect(await screen.findByText(/waiting for an administrator to approve it/)).toBeInTheDocument();
  });

  it("says sign-up is closed when it is switched off", async () => {
    signedOut(undefined, OPTS({ signup: false }));
    renderApp("/signup");
    expect(await screen.findByText("Sign-up is closed")).toBeInTheDocument();
  });
});

describe("approving sign-ups", () => {
  it("an administrator approves a request with a role", async () => {
    const calls = mockApi((url, init) => {
      if (url.endsWith("/me")) return { body: { id: "1", email: "admin@example.com", role: "admin" } };
      if (url.endsWith("/admin/signups")) return { body: { pending: [{ id: "u9", email: "new@example.com", role: "viewer" }] } };
      if (url.includes("/admin/signups/u9/approve") && init?.method === "POST") return { body: { id: "u9", email: "new@example.com", role: "reviewer" } };
      if (url.endsWith("/admin/users")) return { body: [] };
      return { body: {} };
    });
    renderApp("/settings/users");
    const section = (await screen.findByRole("heading", { name: /Waiting for approval/ })).closest("section") as HTMLElement;
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(within(section).getByRole("combobox", { name: "Role for new@example.com" }));
    await u.click(await screen.findByTitle("Reviewer"));
    await u.click(within(section).getByRole("button", { name: "Approve" }));
    await waitFor(() => {
      const c = calls.find((x) => x.url.includes("/approve"));
      expect(c && JSON.parse(String(c.init!.body))).toEqual({ role: "reviewer" });
    });
  });
});
