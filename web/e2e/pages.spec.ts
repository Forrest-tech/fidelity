import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

// Real-user checks for the problems found in the page audit (docs/testing/FINDINGS.md). Each test fails
// without its fix.
const PW = "e2e-password-123";
const ACCOUNT = /^(Account menu|账号菜单)$/;

async function signIn(page: Page, email: string, password = PW) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  // "I'm not a robot": tick it and wait for the green tick, as a person does
  const box = page.getByRole("checkbox", { name: /^(I'm not a robot|我不是机器人)$/ });
  await box.click();
  await expect(box).toHaveAttribute("aria-checked", "true", { timeout: 30_000 });
  await page.getByRole("button", { name: /^(Sign in|登\s?录)$/ }).click();
  await expect(page.getByRole("button", { name: ACCOUNT })).toBeVisible({ timeout: 20_000 });
}

test.describe("users: an administrator manages people", () => {
  test("F-01 add a person, set a new password, switch them off: each takes effect", async ({ page, browser }, info) => {
    test.skip(info.project.name !== "desktop", "one size is enough for this flow");
    test.setTimeout(120_000); // three people sign in; password hashing is deliberately slow
    await signIn(page, "admin@example.com");
    await page.goto("/users");
    const email = `temp-${Date.now()}@example.com`;
    const form = page.getByRole("form", { name: "Add a user" });
    await form.getByLabel("Email").fill(email);
    await form.getByLabel("Password").fill("first-long-password");
    await form.getByRole("button", { name: "Create user" }).click();
    await expect(page.getByRole("cell", { name: new RegExp(`^${email}`) }).first()).toBeVisible({ timeout: 15_000 });

    // the same email again: a sentence, not REGISTER_USER_ALREADY_EXISTS
    await form.getByLabel("Email").fill(email);
    await form.getByLabel("Password").fill("first-long-password");
    await form.getByRole("button", { name: "Create user" }).click();
    await expect(page.getByText("A user with this email already exists.")).toBeVisible();

    const row = page.getByRole("row", { name: new RegExp(email) });
    await row.getByRole("button", { name: "Set password" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("New password").fill("second-long-password");
    await dialog.getByRole("button", { name: "Set password" }).click();
    await expect(page.getByText("New password set.")).toBeVisible({ timeout: 15_000 });

    const ctx = await browser.newContext();
    const other = await ctx.newPage();
    await signIn(other, email, "second-long-password");                                  // the new password works
    await ctx.close();

    await row.getByRole("switch", { name: `${email} can sign in` }).click();
    await expect(page.getByText("Saved.")).toBeVisible({ timeout: 15_000 });
    const ctx2 = await browser.newContext();
    const off = await ctx2.newPage();
    await off.goto("/login");
    await off.getByLabel("Email").fill(email);
    await off.getByLabel("Password").fill("second-long-password");
    const box = off.getByRole("checkbox", { name: "I'm not a robot" });
    await box.click();
    await expect(box).toHaveAttribute("aria-checked", "true", { timeout: 30_000 });
    await off.getByRole("button", { name: /^Sign in$/ }).click();
    await expect(off.getByRole("alert")).toContainText("Wrong email or password", { timeout: 20_000 }); // switched off
    await ctx2.close();
  });

  test("F-01 an administrator cannot lock themselves out", async ({ page }) => {
    await signIn(page, "admin@example.com");
    await page.goto("/users");
    const me = page.getByRole("row", { name: /admin@example\.com/ });
    await expect(me.getByRole("switch")).toBeDisabled();
    await expect(me.getByRole("combobox")).toBeDisabled();
  });
});

test.describe("review: what a viewer sees", () => {
  test("F-02 a viewer gets no controls the server would refuse; a reviewer does", async ({ page, browser }) => {
    await signIn(page, "viewer@example.com");
    await page.goto("/review");
    await expect(page.locator(".legacy-review .header")).toBeVisible({ timeout: 15_000 });
    for (const name of ["Batch score", "Re-run all", "Upload", "Manage"]) await expect(page.getByRole("button", { name, exact: true })).toHaveCount(0);
    await expect(page.getByRole("heading", { level: 1, name: "Review" })).toBeAttached();
    const ctx = await browser.newContext();
    const rev = await ctx.newPage();
    await signIn(rev, "reviewer@example.com");
    await rev.goto("/review");
    await expect(rev.getByRole("button", { name: "Batch score" })).toBeVisible({ timeout: 15_000 });
    await ctx.close();
  });

  test("F-03 the threshold value is not covered by the Mark passing button", async ({ page }, info) => {
    test.skip(info.project.name === "phone", "the file list is a drawer on phones");
    await signIn(page, "reviewer@example.com");
    await page.goto("/review");
    const value = page.locator(".tree-foot b");
    await expect(value).toBeVisible({ timeout: 15_000 });
    const a = (await value.boundingBox())!;
    const b = (await page.locator(".tree-foot > button").boundingBox())!;
    const overlap = a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
    expect(overlap).toBe(false);
  });
});

test.describe("distill and sources: no dead ends", () => {
  test("F-05 a new room says straight away that no cloud storage is connected, and who can fix it", async ({ page }) => {
    await signIn(page, "reviewer@example.com");
    await page.goto("/distill");
    await page.getByRole("button", { name: /New room/ }).click();
    await expect(page.getByRole("region", { name: "New room (not saved)" }).getByRole("alert")).toContainText("Ask an administrator to connect one.");
  });

  test("F-04 a source folder missing on the server is flagged; an existing one can be distilled", async ({ page }) => {
    await signIn(page, "reviewer@example.com");
    await page.goto("/sources");
    await expect(page.getByText("This folder is not found on the server.", { exact: false }).first()).toBeVisible({ timeout: 15_000 });
    const lib = page.locator(".ant-card", { hasText: "E2E library" });
    await expect(lib.getByRole("button", { name: "Distill all PDFs" })).toBeVisible();
  });
});
