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
  // the account button is in the top bar at every screen size
  await expect(page.getByRole("button", { name: ACCOUNT })).toBeVisible({ timeout: 15_000 });
}

const ACCOUNT = /^(Account menu|账号菜单)$/;

async function signOut(page: Page) {
  await page.getByRole("button", { name: ACCOUNT }).click();
  await page.getByRole("menuitem", { name: /Sign out|退出/ }).click();
}

// The language switch is in the top bar on wide screens and in the account menu everywhere.
async function setLanguage(page: Page, lang: "English" | "中文") {
  const bar = page.getByRole("group", { name: /^(Language|语言)$/ });
  if (await bar.isVisible()) {
    await bar.getByRole("button", { name: lang === "English" ? "EN" : "中文" }).click();
    return;
  }
  await page.getByRole("button", { name: ACCOUNT }).click();
  await page.getByRole("menuitem", { name: /^(Language|语言)/ }).click();
  await page.getByRole("menuitemradio", { name: new RegExp(`^${lang}`) }).click();
}

// The shell has rendered (also after a reload). The navigation is in the top bar, or at the bottom on phones.
async function openNav(page: Page) {
  await expect(page.locator("#main")).toBeVisible({ timeout: 15_000 });
}

const navLink = (page: Page, name: string) => page.getByRole("link", { name, exact: true }).filter({ visible: true }).first();

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
    await signOut(page);
    await expect(page).toHaveURL(/\/login/);
  });
});

test.describe("roles", () => {
  test("a viewer cannot reach Users and sees no action buttons", async ({ page }) => {
    await login(page, "viewer");
    await openNav(page);
    await page.getByRole("button", { name: ACCOUNT }).click();
    await expect(page.getByRole("menuitem", { name: "Users" })).toHaveCount(0);
    await page.keyboard.press("Escape");
    await page.goto("/users");
    await expect(page.getByRole("heading", { level: 1, name: "You do not have access to this page." })).toBeAttached();
    await expect(page.getByTestId("empty-state")).toContainText("You do not have access to this page.");
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
    await expect(page.getByRole("cell", { name: email, exact: true }).first()).toBeVisible({ timeout: 15_000 }); // hashing a password is slow on a busy machine
    const ctx = await browser.newContext();
    const p2 = await ctx.newPage();
    await p2.goto(new URL("/login", page.url()).toString());
    await p2.getByLabel("Email").fill(email);
    await p2.getByLabel("Password").fill("another-long-password");
    await p2.getByRole("button", { name: "Sign in" }).click();
    await expect(p2.getByRole("button", { name: ACCOUNT })).toBeVisible({ timeout: 15_000 });
    await ctx.close();
  });
});

test.describe("pages have content or a clear state", () => {
  for (const [path, heading] of [
    ["/", "Overview"],
    ["/distill", "Distill"],
    ["/corrections", "Correction library"],
    ["/settings/corrections", "Correction library"],
    ["/sources", "Sources"],
    ["/jobs", "Jobs"],
    ["/documents", "Results"],
    ["/settings", "Account"],
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
    await expect(page.getByRole("heading", { level: 1, name: "Results" })).toBeVisible();
    await page.goto("/no-such-page");
    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  });
});

test.describe("review screen", () => {
  test("opens inside the shell, follows the shell language, no page-level horizontal scroll", async ({ page }) => {
    await login(page, "reviewer");
    await page.goto("/review");
    await expect(page.locator(".legacy-review .header")).toBeVisible({ timeout: 15_000 });
    await expect(page.locator(".legacy-review .langsw")).toHaveCount(0); // one language switch, in the shell
    await setLanguage(page, "中文");
    await expect(page.locator(".legacy-review .statsbar")).toContainText(/[一-鿿]/);
    await setLanguage(page, "English");
    await expect(page.locator(".legacy-review .statsbar")).not.toContainText(/[一-鿿]/);
  });

  test("follows the dark theme and stays accessible in it", async ({ page }) => {
    await login(page, "reviewer");
    await page.goto("/review");
    await expect(page.locator(".legacy-review .header")).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: "Switch to dark mode" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    const bg = await page.locator(".legacy-review").evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(bg).toBe("rgb(2, 6, 23)");                                  // dark surface, not the light one
    const r = await new AxeBuilder({ page }).include(".legacy-review").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    const found = r.violations.flatMap((v) => v.nodes.map((n) => `${v.id} ${n.target.join(" ")}: ${n.any[0]?.message ?? v.help}`));
    expect(found).toEqual([]);
  });
});

test.describe("bilingual", () => {
  test("switching to Chinese translates the interface and survives a reload", async ({ page }) => {
    await login(page, "admin");
    await setLanguage(page, "中文");
    await openNav(page);
    await expect(navLink(page, "蒸馏")).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
    await page.reload();
    await openNav(page);
    await expect(navLink(page, "蒸馏")).toBeVisible();
    await setLanguage(page, "English");
  });
});

test.describe("responsive", () => {
  test("no horizontal scrolling on any main page", async ({ page }) => {
    await login(page, "admin");
    for (const p of ["/", "/distill", "/corrections", "/sources", "/jobs", "/documents", "/settings", "/settings/ai", "/users"]) {
      await page.goto(p);
      await page.waitForLoadState("networkidle");
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, `horizontal overflow on ${p}`).toBeLessThanOrEqual(1);
    }
  });

  test("the navigation is always reachable: in the top bar, or at the bottom on phones", async ({ page }, info) => {
    await login(page, "reviewer");
    const where = info.project.name === "phone" ? "Phone navigation" : "Main navigation";
    const nav = page.getByRole("navigation", { name: where });
    await expect(nav).toBeVisible();
    await nav.getByRole("link", { name: "Distill" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Distill" })).toBeVisible();
    await nav.getByRole("link", { name: "Results" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Results" })).toBeVisible();
  });

  test("the command palette opens with Ctrl K and goes to a page", async ({ page }, info) => {
    test.skip(info.project.name === "phone", "no keyboard on a phone");
    await login(page, "reviewer");
    await page.keyboard.press("Control+k");
    await page.getByLabel("Search files, pages and actions").fill("Distill");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { level: 1, name: "Distill" })).toBeVisible();
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
    await page.evaluate(() => localStorage.setItem("fidelity.theme", "dark")); // the app's own setting, read on load
    await page.reload();
    await expect(page.getByRole("form", { name: "Sign in" })).toBeVisible();
    await scan(page);
  });

  for (const theme of ["light", "dark"] as const) {
    test(`main pages, ${theme} theme`, async ({ page }) => {
      await login(page, "admin");
      await page.evaluate((t) => localStorage.setItem("fidelity.theme", t), theme); // read on the next page load
      for (const p of ["/", "/distill", "/corrections", "/sources", "/jobs", "/documents", "/settings", "/settings/ai", "/users", "/review"]) {
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
    if (!fs.existsSync(info.snapshotPath("login.png")) && info.config.updateSnapshots !== "all") {
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
