import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

// Sign-in as people do it: the real page, the real bot check solving in the browser, the real redirect
// through a (local) company identity provider. See docs/testing/TEST_CASES.md, section LOGIN.
const PW = "e2e-password-123";
const OIDC = "http://127.0.0.1:8767";
const ACCOUNT = /^(Account menu|账号菜单)$/;

const signInButton = (page: Page) => page.getByRole("button", { name: /^(Sign in|登\s?录)$/ });
// what a person waits for before pressing Sign in (it takes a moment after the page opens or after a failed try)
const checked = (page: Page) => expect(page.getByRole("status", { name: "Bot check" })).toContainText("Bot check passed", { timeout: 30_000 });
const as = (page: Page, q: string) => page.request.get(`${OIDC}/__as?${q}`);

test.describe("sign-in page", () => {
  test("LOGIN-01 looks like a standard sign-in: SSO first, then email and password, with a bot check", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByRole("heading", { level: 1, name: "Sign in to Fidelity" })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("button", { name: "Continue with Company SSO" })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("or", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Email")).toBeFocused(); // ready to type at once
    await expect(page.getByLabel("Password")).toHaveAttribute("type", "password");
    // the bot check runs by itself: nothing to click, no puzzle
    await expect(page.getByRole("status", { name: "Bot check" })).toContainText("Bot check passed", { timeout: 30_000 });
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
    await signInButton(page).click();
    await expect(page.getByRole("alert")).toContainText("Wrong email or password");
    await expect(page).toHaveURL(/\/login/);
    await page.getByLabel("Password").fill(PW);
    await signInButton(page).click();
    await expect(page.getByRole("button", { name: ACCOUNT })).toBeVisible({ timeout: 20_000 });
  });

  test("LOGIN-04 keyboard only: Tab through, Enter signs in, spaces around the email are ignored", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByLabel("Email")).toBeFocused({ timeout: 20_000 });
    await page.keyboard.type("  viewer@example.com ");
    await page.getByLabel("Password").focus();
    await page.keyboard.type(PW);
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: ACCOUNT })).toBeVisible({ timeout: 20_000 });
  });

  test("LOGIN-05 the page asked for comes back after signing in", async ({ page }) => {
    await page.goto("/documents");
    await expect(page).toHaveURL(/\/login/);
    await page.getByLabel("Email").fill("reviewer@example.com");
    await page.getByLabel("Password").fill(PW);
    await signInButton(page).click();
    await expect(page.getByRole("heading", { level: 1, name: "Results" })).toBeVisible({ timeout: 20_000 });
  });

  test("LOGIN-06 no connection: a plain message, the form keeps what was typed", async ({ page }) => {
    await page.goto("/login");
    await page.route("**/api/v1/auth/login", (r) => r.abort("internetdisconnected"));
    await page.getByLabel("Email").fill("reviewer@example.com");
    await page.getByLabel("Password").fill(PW);
    await signInButton(page).click();
    await expect(page.getByRole("alert")).toContainText("Check your connection");
    await expect(page.getByLabel("Email")).toHaveValue("reviewer@example.com");
    await page.unroute("**/api/v1/auth/login");
    await page.route("**/api/v1/auth/login", (r) => r.fulfill({ status: 500, body: "{}" }));
    await checked(page);
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

  test("LOGIN-11 someone without a Fidelity account is told what to do, and stays signed out", async ({ page }) => {
    await as(page, "email=stranger@example.org&verified=1");
    await page.goto("/login");
    await page.getByRole("button", { name: "Continue with Company SSO" }).click();
    await expect(page.getByRole("alert")).toContainText("not registered in Fidelity");
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
    await expect(page.getByRole("status", { name: "Bot check" })).toContainText("Bot check passed", { timeout: 30_000 });
    await page.getByLabel("Email").fill("viewer@example.com");
    await page.getByLabel("Password").fill(PW);
    await signInButton(page).click();
    await expect(page.getByRole("button", { name: ACCOUNT })).toBeVisible({ timeout: 20_000 });
    await browser.close();
  });
});
