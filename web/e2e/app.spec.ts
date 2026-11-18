import fs from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

const PW = "e2e-password-123";

async function login(page: Page, role: "admin" | "reviewer" | "viewer") {
  await page.goto("/login");
  await page.getByLabel("Email").fill(`${role}@example.com`);
  await page.getByLabel("Password").fill(PW);
  await page.getByRole("button", { name: "Sign in" }).click();
  // the sign-out button is visible at every screen size (the navigation is behind a menu on phones)
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible({ timeout: 15_000 });
}

// On a phone the navigation sits behind a Menu button.
async function openNav(page: Page) {
  await expect(page.locator("#main")).toBeVisible({ timeout: 15_000 }); // shell rendered (also after a reload)
  const menu = page.locator('button[aria-controls="side-nav"]'); // label changes with the language
  if (await menu.isVisible()) {
    if ((await menu.getAttribute("aria-expanded")) !== "true") await menu.click();
  }
}

test.describe("sign in and out", () => {
  test("anonymous visitors are sent to the login page", async ({ page }) => {
    await page.goto("/sources");
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByRole("form", { name: "Sign in" })).toBeVisible();
  });

  test("wrong password shows an error and stays on the login page", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill("admin@example.com");
    await page.getByLabel("Password").fill("not-the-password");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("alert")).toContainText("Wrong email or password");
  });

  test("sign in, reload keeps the session, sign out returns to login", async ({ page }) => {
    await login(page, "reviewer");
    await page.reload();
    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login/);
  });
});

test.describe("roles", () => {
  test("a viewer cannot reach Users and sees no action buttons", async ({ page }) => {
    await login(page, "viewer");
    await openNav(page);
    await expect(page.getByRole("link", { name: "Users" })).toHaveCount(0);
    await page.goto("/users");
    await expect(page.getByText("You do not have access to this page.")).toBeVisible();
    await page.goto("/sources");
    await expect(page.getByRole("heading", { name: "Sources" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Distill all PDFs" })).toHaveCount(0);
  });

  test("a reviewer sees the distill actions", async ({ page }) => {
    await login(page, "reviewer");
    await page.goto("/sources");
    await expect(page.getByRole("button", { name: "Distill all PDFs" }).first()).toBeVisible();
  });

  test("an administrator can create a user who can then sign in", async ({ page, browser }) => {
    await login(page, "admin");
    await page.goto("/users");
    const form = page.getByRole("form", { name: "Add a user" });
    const email = `new-${Date.now()}@example.com`;
    await form.getByLabel("Email").fill(email);
    await form.getByLabel(/Password/).fill("another-long-password");
    await form.getByRole("button", { name: "Create user" }).click();
    await expect(page.getByRole("cell", { name: email })).toBeVisible();
    const ctx = await browser.newContext();
    const p2 = await ctx.newPage();
    await p2.goto(new URL("/login", page.url()).toString());
    await p2.getByLabel("Email").fill(email);
    await p2.getByLabel("Password").fill("another-long-password");
    await p2.getByRole("button", { name: "Sign in" }).click();
    await expect(p2.getByRole("button", { name: "Sign out" })).toBeVisible({ timeout: 15_000 });
    await ctx.close();
  });
});

test.describe("pages have content or a clear state", () => {
  for (const [path, heading] of [
    ["/", "Overview"],
    ["/sources", "Sources"],
    ["/jobs", "Jobs"],
    ["/documents", "Documents"],
    ["/settings", "Settings"],
  ] as const) {
    test(`${path} renders`, async ({ page }) => {
      await login(page, "reviewer");
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
      await expect(page.getByText("Loading…")).toHaveCount(0, { timeout: 10_000 });
    });
  }

  test("an unknown path returns to the overview and a reload of a deep link works", async ({ page }) => {
    await login(page, "reviewer");
    await page.goto("/documents");
    await page.reload();
    await expect(page.getByRole("heading", { name: "Documents" })).toBeVisible();
    await page.goto("/no-such-page");
    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  });
});

test.describe("bilingual", () => {
  test("switching to Chinese translates the interface and survives a reload", async ({ page }) => {
    await login(page, "admin");
    await page.getByLabel("Language").selectOption("zh");
    await openNav(page);
    await expect(page.getByRole("link", { name: "数据源" })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
    await page.reload();
    await openNav(page);
    await expect(page.getByRole("link", { name: "数据源" })).toBeVisible();
    await page.getByLabel("语言").selectOption("en");
  });
});

test.describe("responsive", () => {
  test("no horizontal scrolling on any main page", async ({ page }) => {
    await login(page, "admin");
    for (const p of ["/", "/sources", "/jobs", "/documents", "/settings", "/users"]) {
      await page.goto(p);
      await page.waitForLoadState("networkidle");
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, `horizontal overflow on ${p}`).toBeLessThanOrEqual(1);
    }
  });

  test("on narrow screens the menu button toggles the navigation", async ({ page }) => {
    await login(page, "reviewer");
    const menu = page.getByRole("button", { name: "Menu" });
    test.skip(!(await menu.isVisible()), "wide layout shows the navigation permanently");
    await expect(menu).toHaveAttribute("aria-expanded", "false");
    await menu.click();
    await expect(page.getByRole("link", { name: "Jobs" })).toBeVisible();
    await page.getByRole("link", { name: "Jobs" }).click();
    await expect(page.getByRole("heading", { name: "Jobs" })).toBeVisible();
  });
});

test.describe("accessibility (axe-core)", () => {
  test.setTimeout(120_000); // six full-page scans per test on a slow machine
  const scan = async (page: Page) => {
    const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    const found = r.violations.flatMap((v) =>
      v.nodes.map((n) => `${v.id} @ ${page.url().replace(/^https?:\/\/[^/]+/, "")} ${n.target.join(" ")}: ${n.any[0]?.message ?? v.help}`),
    );
    expect(found).toEqual([]);
  };

  test("login page, light and dark", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByRole("form", { name: "Sign in" })).toBeVisible();
    await scan(page);
    await page.evaluate(() => (document.documentElement.dataset.theme = "dark"));
    await scan(page);
  });

  for (const theme of ["light", "dark"] as const) {
    test(`main pages, ${theme} theme`, async ({ page }) => {
      await login(page, "admin");
      await page.getByLabel("Theme").selectOption(theme);
      for (const p of ["/", "/sources", "/jobs", "/documents", "/settings", "/users"]) {
        await page.goto(p);
        await page.waitForLoadState("networkidle");
        await openNav(page);
        await scan(page);
      }
    });
  }
});

test.describe("visual regression", () => {
  test("login and overview", async ({ page }, info) => {
    test.skip(info.project.name !== "desktop", "baselines are kept for the desktop size only");
    // Baselines are made on Linux in CI (spec section 9). Until they are committed for this
    // platform, record the current screens as an artifact instead of failing.
    if (!fs.existsSync(info.snapshotPath("login.png"))) {
      await page.goto("/login");
      await page.screenshot({ path: info.outputPath("login.png") });
      await login(page, "reviewer");
      await page.waitForLoadState("networkidle");
      await page.screenshot({ path: info.outputPath("overview.png") });
      test.skip(true, `no visual baseline for ${process.platform} yet; screenshots saved to test-results`);
    }
    await page.goto("/login");
    await expect(page).toHaveScreenshot("login.png", { maxDiffPixelRatio: 0.01 });
    await login(page, "reviewer");
    await page.waitForLoadState("networkidle");
    await expect(page).toHaveScreenshot("overview.png", { maxDiffPixelRatio: 0.01, mask: [page.locator("header, [data-volatile]")] });
  });
});
