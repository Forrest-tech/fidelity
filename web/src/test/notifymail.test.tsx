import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockApi, renderApp } from "./helpers";

const ME = (role: string) => ({ id: "1", email: "a@example.com", role });

describe("notification e-mails", () => {
  it("lets a reviewer switch the e-mails off, and says when no mail server is set up", async () => {
    let on = true;
    const calls = mockApi((url, init) => {
      if (url.endsWith("/me")) return { body: ME("reviewer") };
      if (url.endsWith("/notifications/email")) {
        if (init?.method === "PUT") on = JSON.parse(String(init.body)).email;
        return { body: { email: on, eligible: true, mail_ready: false } };
      }
      return { body: { items: [], unread: 0 } };
    });
    renderApp("/settings/notifications");
    const box = await screen.findByRole("checkbox", { name: /Also e-mail me what the bell shows/ });
    expect(box).toBeChecked();
    expect(screen.getByText(/No mail server is set up yet/)).toBeInTheDocument();
    await userEvent.setup().click(box);
    await waitFor(() => expect(screen.getByRole("checkbox", { name: /Also e-mail me/ })).not.toBeChecked());
    expect(calls.some((c) => c.url.endsWith("/notifications/email") && c.init?.method === "PUT")).toBe(true);
  });

  it("does not offer it to a viewer", async () => {
    mockApi((url) => {
      if (url.endsWith("/me")) return { body: ME("viewer") };
      if (url.endsWith("/notifications/email")) return { body: { email: true, eligible: false, mail_ready: true } };
      return { body: { items: [], unread: 0 } };
    });
    renderApp("/settings/notifications");
    await screen.findAllByText(/Notifications/);
    expect(screen.queryByRole("checkbox", { name: /Also e-mail me/ })).not.toBeInTheDocument();
  });
});
