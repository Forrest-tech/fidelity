import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderApp } from "./helpers";

const optsTurnstile = { providers: [], captcha: true, signup: true, email: true, captcha_provider: "turnstile", turnstile_site_key: "1x00000000000000000000AA" };

afterEach(() => {
  delete (window as { turnstile?: unknown }).turnstile;
  document.head.querySelectorAll('script[src*="challenges.cloudflare.com"]').forEach((s) => s.remove());
});

describe("Cloudflare Turnstile as the human check", () => {
  it("shows Cloudflare's widget and sends its token with the sign-up", async () => {
    let cb: ((t: string) => void) | undefined;
    const render = vi.fn((_el: HTMLElement, o: Record<string, unknown>) => {
      cb = o.callback as (t: string) => void;
      return "w1";
    });
    (window as { turnstile?: unknown }).turnstile = { render, reset: vi.fn(), remove: vi.fn() };
    const calls = mockApi((url) => {
      if (url.endsWith("/me")) return { status: 401, body: { detail: "Unauthorized" } };
      if (url.endsWith("/auth/options")) return { body: optsTurnstile };
      if (url.endsWith("/auth/signup")) return { status: 201, body: { status: "verify_email" } };
      return { body: {} };
    });
    renderApp("/signup");
    await waitFor(() => expect(render).toHaveBeenCalled());
    expect(render.mock.calls[0][1]).toMatchObject({ sitekey: "1x00000000000000000000AA" });
    expect(screen.queryByRole("checkbox", { name: /not a robot/i })).toBeNull();   // no second box
    cb!("TOKEN-123");
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.type(screen.getByLabelText("Email"), "new@example.com");
    await u.type(screen.getByLabelText("Password"), "abcd1234");
    await u.type(screen.getByLabelText("Confirm password"), "abcd1234");
    await u.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/auth/signup"))).toBe(true));
    const body = JSON.parse(String(calls.find((c) => c.url.endsWith("/auth/signup"))!.init!.body));
    expect(body).toMatchObject({ email: "new@example.com", password: "abcd1234", altcha: "turnstile:TOKEN-123" });
  });

  it("falls back to the built-in check when Cloudflare's script cannot load", async () => {
    const append = document.head.appendChild.bind(document.head);
    const spy = vi.spyOn(document.head, "appendChild").mockImplementation(<T extends Node>(n: T): T => {
      const el = n as unknown as HTMLScriptElement;
      if (el.tagName === "SCRIPT" && el.src.includes("challenges.cloudflare.com")) {
        setTimeout(() => el.onerror?.(new Event("error")), 0);
        return n;
      }
      return append(n);
    });
    mockApi((url) => {
      if (url.endsWith("/me")) return { status: 401, body: { detail: "Unauthorized" } };
      if (url.endsWith("/auth/options")) return { body: optsTurnstile };
      return { body: {} };
    });
    renderApp("/signup");
    expect(await screen.findByRole("checkbox", { name: /not a robot/i })).toBeInTheDocument();
    spy.mockRestore();
  });

  it("an administrator enters the Turnstile keys; the secret is shown only as dots", async () => {
    const calls = mockApi((url, init) => {
      if (url.endsWith("/me")) return { body: { id: "1", email: "admin@example.com", role: "admin" } };
      if (url.endsWith("/admin/captcha") && init?.method === "PUT") return { body: { provider: "turnstile", site_key: "0x4AAA", secret_set: true, active: "turnstile" } };
      if (url.endsWith("/admin/captcha")) return { body: { provider: "altcha", site_key: "", secret_set: false, active: "altcha" } };
      return { body: {} };
    });
    renderApp("/settings/captcha");
    expect(await screen.findByText(/built-in check is on/)).toBeInTheDocument();
    const u = userEvent.setup({ pointerEventsCheck: 0 });
    await u.click(screen.getByRole("radio", { name: "Cloudflare Turnstile" }));
    await u.type(screen.getByLabelText("Turnstile site key"), "0x4AAA");
    await u.type(screen.getByLabelText(/^Turnstile secret key/), "0x4SECRET");
    await u.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.init?.method === "PUT")).toBe(true));
    expect(JSON.parse(String(calls.find((c) => c.init?.method === "PUT")!.init!.body))).toEqual({ provider: "turnstile", site_key: "0x4AAA", secret_key: "0x4SECRET" });
    expect(await screen.findByText(/Cloudflare Turnstile is on/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Turnstile secret key/)).toHaveValue("••••••••");
  });
});
