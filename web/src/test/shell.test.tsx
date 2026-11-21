import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import i18n from "../locales";
import { mockApi, renderApp } from "./helpers";

const ME = (role: string) => ({ id: "1", email: "a@example.com", role });
const SRC = [{ id: "n2", name: "N2 library", src_root: "C:/lib", md_root: "C:/md" }];

describe("auth guard", () => {
  it("sends an anonymous visitor to the login page", async () => {
    mockApi((url) => (url.endsWith("/me") ? { status: 401, body: { detail: "Unauthorized" } } : { body: [] }));
    renderApp("/sources");
    expect(await screen.findByRole("form", { name: /sign in/i })).toBeInTheDocument();
  });

  it("shows the shell with navigation once signed in", async () => {
    mockApi((url) => (url.endsWith("/me") ? { body: ME("reviewer") } : { body: [] }));
    renderApp("/");
    const nav = await screen.findByRole("navigation", { name: "Main navigation" });
    expect(nav).toHaveTextContent("Overview");
    expect(nav).toHaveTextContent("Distill");
    expect(nav).not.toHaveTextContent("Users"); // admin only
    await userEvent.setup().click(screen.getByRole("button", { name: "Account menu" }));
    expect(await screen.findByRole("menuitem", { name: "Settings" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Users" })).not.toBeInTheDocument();
  });

  it("shows the Users link to admins", async () => {
    mockApi((url) => (url.endsWith("/me") ? { body: ME("admin") } : { body: [] }));
    renderApp("/");
    await userEvent.setup().click(await screen.findByRole("button", { name: "Account menu" }));
    expect(await screen.findByRole("menuitem", { name: "Users" })).toBeInTheDocument();
  });

  it("blocks a non-admin from /users", async () => {
    mockApi((url) => (url.endsWith("/me") ? { body: ME("viewer") } : { body: [] }));
    renderApp("/users");
    expect(await screen.findByText(/do not have access/i)).toBeInTheDocument();
  });
});

describe("login", () => {
  it("signs in, and shows a clear message for a wrong password", async () => {
    let signedIn = false;
    mockApi((url, init) => {
      if (url.endsWith("/me")) return signedIn ? { body: ME("viewer") } : { status: 401, body: {} };
      if (url.endsWith("/auth/login")) {
        if (String(init?.body).includes("good")) {
          signedIn = true;
          return { status: 204 };
        }
        return { status: 400, body: { detail: "LOGIN_BAD_CREDENTIALS" } };
      }
      return { body: [] };
    });
    renderApp("/");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "a@example.com");
    await user.type(screen.getByLabelText("Password"), "bad-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong email or password");
    await user.clear(screen.getByLabelText("Password"));
    await user.type(screen.getByLabelText("Password"), "good-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(screen.getByRole("navigation", { name: "Main navigation" })).toBeInTheDocument());
  });

  it("tells the user when too many attempts were made", async () => {
    mockApi((url) => (url.endsWith("/me") ? { status: 401, body: {} } : { status: 429, body: { detail: "too many" } }));
    renderApp("/");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "a@example.com");
    await user.type(screen.getByLabelText("Password"), "x");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/too many failed attempts/i);
  });
});

describe("language and page states", () => {
  it("switches the interface between English and Chinese and remembers it", async () => {
    mockApi((url) => (url.endsWith("/me") ? { body: ME("admin") } : { body: [] }));
    renderApp("/");
    const user = userEvent.setup();
    await screen.findByRole("navigation", { name: "Main navigation" });
    await user.click(within(screen.getByRole("group", { name: "Language" })).getByRole("button", { name: "中文" }));
    expect(await within(screen.getByRole("navigation", { name: "主导航" })).findByRole("link", { name: "蒸馏" })).toBeInTheDocument();
    expect(localStorage.getItem("fidelity.lang")).toBe("zh");
    await i18n.changeLanguage("en");
  });

  it("sources page: empty state", async () => {
    mockApi((url) => (url.endsWith("/me") ? { body: ME("viewer") } : { body: [] }));
    renderApp("/sources");
    expect(await screen.findByTestId("empty-state")).toHaveTextContent("No sources configured");
  });

  it("sources page: data state", async () => {
    mockApi((url) => (url.endsWith("/me") ? { body: ME("viewer") } : { body: SRC }));
    renderApp("/sources");
    expect(await screen.findByText("N2 library")).toBeInTheDocument();
  });

  it("sources page: error state that can be retried", async () => {
    let fail = true;
    mockApi((url) => {
      if (url.endsWith("/me")) return { body: ME("viewer") };
      return fail ? { status: 500, body: { detail: "boom" } } : { body: SRC };
    });
    renderApp("/sources");
    const user = userEvent.setup();
    expect(await screen.findByTestId("error-state")).toHaveTextContent("boom");
    fail = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("N2 library")).toBeInTheDocument();
  });

  it("every placeholder page has an empty state, never a blank screen", async () => {
    for (const p of ["/", "/jobs", "/documents"]) {
      mockApi((url) => (url.endsWith("/me") ? { body: ME("viewer") } : { body: [] }));
      const { unmount } = renderApp(p);
      expect(await screen.findByTestId("empty-state")).toBeInTheDocument();
      unmount();
    }
  });
});
