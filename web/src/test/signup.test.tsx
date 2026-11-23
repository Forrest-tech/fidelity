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

describe("email: confirm, reset, settings", () => {
  it("the confirmation link confirms the address and says what happens next", async () => {
    const calls = signedOut((url, init) => (url.endsWith("/auth/verify-email") && init?.method === "POST" ? { body: { status: "pending" } } : undefined));
    renderApp("/verify-email?token=abc.def");
    expect(await screen.findByText("Email address confirmed")).toBeInTheDocument();
    expect(screen.getByText(/administrator will now approve/)).toBeInTheDocument();
    expect(JSON.parse(String(calls.find((c) => c.url.endsWith("/auth/verify-email"))!.init!.body))).toEqual({ token: "abc.def" });
  });

  it("a broken confirmation link offers to send a new one", async () => {
    signedOut((url) => (url.endsWith("/auth/verify-email") ? { status: 400, body: { detail: "LINK_INVALID" } } : undefined));
    renderApp("/verify-email?token=bad");
    expect(await screen.findByText("This link does not work")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Send the confirmation email again" })).toHaveAttribute("href", "/resend-confirmation");
  });

  it("forgot password sends a link and never says whether the address has an account", async () => {
    signedOut((url, init) => (url.endsWith("/auth/forgot-password") && init?.method === "POST" ? { body: { status: "sent_if_account" } } : undefined),
      OPTS({ email: true }));
    renderApp("/forgot-password");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.type(await screen.findByLabelText("Email"), "someone@example.com");
    await u.click(screen.getByRole("button", { name: "Send the link" }));
    expect(await screen.findByText(/If someone@example.com has a Fidelity account/)).toBeInTheDocument();
  });

  it("the reset link lets a person choose a new password", async () => {
    const calls = signedOut((url, init) => (url.endsWith("/auth/reset-password") && init?.method === "POST" ? { body: { status: "reset" } } : undefined));
    renderApp("/reset-password?token=t0k");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.type(await screen.findByLabelText("New password"), "a-brand-new-password");
    await u.type(screen.getByLabelText("Confirm password"), "a-brand-new-password");
    await u.click(screen.getByRole("button", { name: "Save the new password" }));
    expect(await screen.findByText("Password changed")).toBeInTheDocument();
    expect(JSON.parse(String(calls.find((c) => c.url.endsWith("/auth/reset-password"))!.init!.body))).toEqual({ token: "t0k", password: "a-brand-new-password" });
  });

  it("signing in before confirming says so and links to a new confirmation email", async () => {
    signedOut((url) => (url.endsWith("/auth/login") ? { status: 403, body: { detail: "EMAIL_NOT_CONFIRMED" } } : undefined));
    renderApp("/login");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.type(await screen.findByLabelText("Email"), "new@example.com");
    await u.type(screen.getByLabelText("Password"), "a-new-long-password");
    await u.click(screen.getByRole("button", { name: /^Sign in$/ }));
    expect(await screen.findByText(/Confirm your email address first/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Send the confirmation email again" })).toBeInTheDocument();
  });

  it("an administrator sets up the mail server; the password is never shown back", async () => {
    const calls = mockApi((url, init) => {
      if (url.endsWith("/me")) return { body: { id: "1", email: "admin@example.com", role: "admin" } };
      if (url.endsWith("/admin/email") && init?.method === "PUT") return { body: { host: "smtp.example.com", port: 587, security: "starttls", username: "f", from_address: "f@example.com", from_name: "Fidelity", site_url: "", approval: "domains", password_set: true, configured: true } };
      if (url.endsWith("/admin/email")) return { body: { host: "", port: 587, security: "starttls", username: "", from_address: "", from_name: "Fidelity", site_url: "", approval: "domains", password_set: false, configured: false } };
      return { body: {} };
    });
    renderApp("/settings/email");
    expect(await screen.findByText(/Not set up yet/)).toBeInTheDocument();
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.type(screen.getByLabelText("SMTP server"), "smtp.example.com");
    await u.type(screen.getByLabelText(/^Password/), "app-pass-123");
    await u.type(screen.getByLabelText("Sender address"), "f@example.com");
    await u.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/admin/email") && c.init?.method === "PUT")).toBe(true));
    const body = JSON.parse(String(calls.find((c) => c.init?.method === "PUT")!.init!.body));
    expect(body).toMatchObject({ host: "smtp.example.com", password: "app-pass-123", from_address: "f@example.com" });
    expect(await screen.findByText("Sending email is set up.")).toBeInTheDocument();
    expect(screen.getByLabelText(/^Password/)).toHaveValue("••••••••");     // saved: shown masked, never the text
    expect(calls.some((c) => c.url.endsWith("/admin/email/password"))).toBe(false);
  });

  it("a saved password shows as dots, Show fetches it on request, and the page names what is missing", async () => {
    const calls = mockApi((url) => {
      if (url.endsWith("/me")) return { body: { id: "1", email: "admin@example.com", role: "admin" } };
      if (url.endsWith("/admin/email/password")) return { body: { password: "abcd efgh ijkl mnop" } };
      if (url.endsWith("/admin/email")) return { body: { host: "smtp.gmail.com", port: 587, security: "starttls", username: "me@gmail.com", from_address: "", from_name: "Fidelity", site_url: "", approval: "domains", password_set: true, configured: false, missing: ["from_address"] } };
      return { body: {} };
    });
    renderApp("/settings/email");
    expect(await screen.findByText(/Still needed: Sender address\./)).toBeInTheDocument();
    const pw = screen.getByLabelText(/^Password/);
    expect(pw).toHaveValue("••••••••");
    expect(pw).toHaveAttribute("type", "password");
    expect(screen.getByLabelText("Sender address")).toHaveAttribute("placeholder", "me@gmail.com");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(screen.getByRole("button", { name: "Show" }));
    await waitFor(() => expect(pw).toHaveValue("abcd efgh ijkl mnop"));
    expect(pw).toHaveAttribute("type", "text");
    expect(calls.filter((c) => c.url.endsWith("/admin/email/password"))).toHaveLength(1);
    await u.click(screen.getByRole("button", { name: "Hide" }));
    expect(pw).toHaveValue("••••••••");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();        // nothing changed, nothing to save
  });
});
