import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

// Sign-in as people do it: the real page, the real bot check solving in the browser, the real redirect
// through a (local) company identity provider. See docs/testing/TEST_CASES.md, section LOGIN.
const PW = process.env.E2E_PASSWORD!; // made per run in playwright.config.ts, never written in the code
const OIDC = "http://127.0.0.1:8767";
const ACCOUNT = /^(Account menu|账号菜单)$/;

const signInButton = (page: Page) => page.getByRole("button", { name: /^(Sign in|登\s?录)$/ });
// "I'm not a robot": tick the box and wait for the green tick, as a person does
async function tick(page: Page) {
  const box = page.getByRole("checkbox", { name: /^(I'm not a robot|我不是机器人)$/ });
  await box.click();
  await expect(box).toHaveAttribute("aria-checked", "true", { timeout: 30_000 });
}
const as = (page: Page, q: string) => page.request.get(`${OIDC}/__as?${q}`);

test.describe("sign-in page", () => {
  test("LOGIN-01 looks like a standard sign-in: SSO first, then email and password, with a bot check", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByRole("heading", { level: 1, name: "Sign in to Fidelity" })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("button", { name: "Continue with Company SSO" })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("or", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Email")).toBeFocused(); // ready to type at once
    await expect(page.getByLabel("Password")).toHaveAttribute("type", "password");
    // the familiar "I'm not a robot" box: unticked at first, a green tick after one click, no puzzle
    const box = page.getByRole("checkbox", { name: "I'm not a robot" });
    await expect(box).toHaveAttribute("aria-checked", "false");
    await tick(page);
    await expect(page.getByRole("link", { name: "Create an account" })).toBeVisible();
  });

  test("LOGIN-02 empty and malformed input is caught on the page, without a request", async ({ page }) => {
    await page.goto("/login");
    let posted = 0;
    page.on("request", (r) => r.url().endsWith("/auth/login") && posted++);
    await signInButton(page).click();
    await expect(page.getByText("Enter your email address.")).toBeVisible();
    await expect(page.getByText("Enter your password.")).toBeVisible();
    await page.getByLabel("Email").fill("not-an-email");
    await page.getByLabel("Password").fill("x");
    await signInButton(page).click();
    await expect(page.getByText(/Enter a valid email address/)).toBeVisible();
    await page.getByLabel("Email").fill("   ");
    await signInButton(page).click();
    await expect(page.getByText("Enter your email address.")).toBeVisible();
    expect(posted).toBe(0);
  });

  test("LOGIN-03 a wrong password says so; the next try (with a fresh bot check) signs in", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill("reviewer@example.com");
    await page.getByLabel("Password").fill("not-the-password");
    await tick(page);
    await signInButton(page).click();
    await expect(page.getByRole("alert")).toContainText("Wrong email or password");
    await expect(page).toHaveURL(/\/login/);
    // the check works once: the box is cleared and is ticked again for the next try
    await expect(page.getByRole("checkbox", { name: "I'm not a robot" })).toHaveAttribute("aria-checked", "false");
    await page.getByLabel("Password").fill(PW);
    await tick(page);
    await signInButton(page).click();
    await expect(page.getByRole("button", { name: ACCOUNT })).toBeVisible({ timeout: 20_000 });
  });

  test("LOGIN-04 keyboard only: Tab through, Enter signs in, spaces around the email are ignored", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByLabel("Email")).toBeFocused({ timeout: 20_000 });
    await page.keyboard.type("  viewer@example.com ");
    await page.getByLabel("Password").focus();
    await page.keyboard.type(PW);
    await page.getByRole("checkbox", { name: "I'm not a robot" }).focus();
    await page.keyboard.press("Space");                    // the box is ticked from the keyboard
    await expect(page.getByRole("checkbox", { name: "I'm not a robot" })).toHaveAttribute("aria-checked", "true", { timeout: 30_000 });
    await page.getByLabel("Password").press("Enter");
    await expect(page.getByRole("button", { name: ACCOUNT })).toBeVisible({ timeout: 20_000 });
  });

  test("LOGIN-05 the page asked for comes back after signing in", async ({ page }) => {
    await page.goto("/documents");
    await expect(page).toHaveURL(/\/login/);
    await page.getByLabel("Email").fill("reviewer@example.com");
    await page.getByLabel("Password").fill(PW);
    await tick(page);
    await signInButton(page).click();
    await expect(page.getByRole("heading", { level: 1, name: "Results" })).toBeVisible({ timeout: 20_000 });
  });

  test("LOGIN-06 no connection: a plain message, the form keeps what was typed", async ({ page }) => {
    await page.goto("/login");
    await page.route("**/api/v1/auth/login", (r) => r.abort("internetdisconnected"));
    await page.getByLabel("Email").fill("reviewer@example.com");
    await page.getByLabel("Password").fill(PW);
    await tick(page);
    await signInButton(page).click();
    await expect(page.getByRole("alert")).toContainText("Check your connection");
    await expect(page.getByLabel("Email")).toHaveValue("reviewer@example.com");
    await page.unroute("**/api/v1/auth/login");
    await page.route("**/api/v1/auth/login", (r) => r.fulfill({ status: 500, body: "{}" }));
    await tick(page);
    await page.getByLabel("Password").press("Enter"); // the second try from the keyboard
    await expect(page.getByRole("alert")).toContainText("Check your connection");
  });

  test("LOGIN-07 forgot password explains who resets it", async ({ page }) => {
    await page.goto("/login");
    await page.getByRole("button", { name: "Forgot password?" }).click();
    await expect(page.getByText(/reset by an administrator/)).toBeVisible();
  });

  test("LOGIN-08 Chinese: the page and its messages are in Chinese", async ({ page }) => {
    await page.goto("/login");
    await page.getByText("中文", { exact: true }).click();
    await expect(page.getByRole("heading", { level: 1, name: "登录 Fidelity" })).toBeVisible();
    await page.getByRole("button", { name: /^登\s?录$/ }).click(); // antd spaces two-character Chinese labels
    await expect(page.getByText("请输入邮箱地址。")).toBeVisible();
    await page.getByText("English").click();
  });

  test("LOGIN-09 phone width: one column, no sideways scrolling, buttons full width", async ({ page }, info) => {
    test.skip(info.project.name !== "phone", "phone layout only");
    await page.goto("/login");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    const btn = await signInButton(page).boundingBox();
    expect(btn!.width).toBeGreaterThan(280);
  });
});

test.describe("sign in with the company identity provider (OpenID Connect)", () => {
  test("LOGIN-10 a registered person signs in with one click and lands where they were going", async ({ page }) => {
    await as(page, "email=reviewer@example.com&verified=1");
    await page.goto("/documents");
    await page.getByRole("button", { name: "Continue with Company SSO" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Results" })).toBeVisible({ timeout: 20_000 });
    await page.getByRole("button", { name: ACCOUNT }).click();
    await expect(page.getByText("reviewer@example.com")).toBeVisible();
  });

  test("LOGIN-11 someone without a Fidelity account becomes a request for approval, and stays signed out", async ({ page }) => {
    await as(page, "email=stranger@example.org&verified=1");
    await page.goto("/login");
    await page.getByRole("button", { name: "Continue with Company SSO" }).click();
    await expect(page.getByRole("alert")).toContainText("with an administrator");
    await expect(page).toHaveURL(/\/login$/); // the error code is not left in the address
    await page.goto("/");
    await expect(page).toHaveURL(/\/login/);
  });

  test("LOGIN-12 an unverified address is refused; cancelling at the provider is understood", async ({ page }) => {
    await as(page, "email=reviewer@example.com&verified=0");
    await page.goto("/login");
    await page.getByRole("button", { name: "Continue with Company SSO" }).click();
    await expect(page.getByRole("alert")).toContainText("verified email");
    await as(page, "deny=1");
    await page.getByRole("button", { name: "Continue with Company SSO" }).click();
    await expect(page.getByRole("alert")).toContainText("cancelled");
    await as(page, "deny=0&email=reviewer@example.com&verified=1");
  });
});

test.describe("office network", () => {
  test("LOGIN-13 works on a plain-HTTP office address (no HTTPS, so no WebCrypto)", async ({ playwright }, info) => {
    test.skip(info.project.name !== "desktop", "one size is enough");
    // fidelity.lan -> 127.0.0.1: not localhost and not HTTPS, so the page is not a secure context,
    // exactly like http://10.0.0.150:8000 in the office
    const browser = await playwright.chromium.launch({ args: ["--host-resolver-rules=MAP fidelity.lan 127.0.0.1"] });
    const page = await browser.newPage();
    const base = new URL(info.project.use.baseURL ?? "http://127.0.0.1:8765");
    await page.goto(`http://fidelity.lan:${base.port}/login`);
    expect(await page.evaluate(() => window.isSecureContext)).toBe(false);
    await page.getByLabel("Email").fill("viewer@example.com");
    await page.getByLabel("Password").fill(PW);
    await tick(page);
    await signInButton(page).click();
    await expect(page.getByRole("button", { name: ACCOUNT })).toBeVisible({ timeout: 20_000 });
    await browser.close();
  });
});

test.describe("sign-up", () => {
  test("LOGIN-14 pressing Sign in without ticking the box asks for it, without a request", async ({ page }) => {
    await page.goto("/login");
    let posted = 0;
    page.on("request", (r) => r.url().endsWith("/auth/login") && posted++);
    await page.getByLabel("Email").fill("reviewer@example.com");
    await page.getByLabel("Password").fill(PW);
    await signInButton(page).click();
    await expect(page.getByRole("alert")).toContainText("Tick “I'm not a robot” first");
    await expect(page.getByRole("checkbox", { name: "I'm not a robot" })).toBeFocused();
    expect(posted).toBe(0);
  });

  test("LOGIN-15 anyone can ask for an account; it waits for an administrator, who approves it", async ({ page, browser }) => {
    test.slow();                                    // sign-up, two sign-ins and an approval: more steps than most
    const email = `new-${Date.now()}@example.net`;
    await page.goto("/login");
    await page.getByRole("link", { name: "Create an account" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Create your account" })).toBeVisible();
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill("a-new-long-password");
    await page.getByLabel("Confirm password").fill("a-new-long-password");
    await tick(page);
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByText("Request sent")).toBeVisible({ timeout: 20_000 });
    // before approval: the right password says the account is waiting
    await page.getByRole("link", { name: "Back to sign in" }).click();
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill("a-new-long-password");
    await tick(page);
    await signInButton(page).click();
    await expect(page.getByRole("alert")).toContainText("waiting for an administrator");
    // an administrator approves it as a reviewer
    const ctx = await browser.newContext();
    const admin = await ctx.newPage();
    await admin.goto(new URL("/login", page.url()).toString());
    await admin.getByLabel("Email").fill("admin@example.com");
    await admin.getByLabel("Password").fill(PW);
    await tick(admin);
    await signInButton(admin).click();
    await expect(admin.getByRole("button", { name: ACCOUNT })).toBeVisible({ timeout: 20_000 });   // signed in first
    await admin.goto(new URL("/settings/users", page.url()).toString());
    await expect(admin.getByRole("heading", { name: /Waiting for approval/ })).toBeVisible({ timeout: 20_000 });
    const row = admin.getByRole("listitem").filter({ hasText: email });
    await row.getByRole("button", { name: "Approve" }).click();              // as a viewer, the default role
    await expect(admin.getByText(`${email} can now sign in`)).toBeVisible({ timeout: 15_000 });
    await ctx.close();
    // now the person signs in
    await tick(page);
    await signInButton(page).click();
    await expect(page.getByRole("button", { name: ACCOUNT })).toBeVisible({ timeout: 20_000 });
  });
});
