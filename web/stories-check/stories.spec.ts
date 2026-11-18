import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import fs from "node:fs";

const index = JSON.parse(fs.readFileSync("storybook-static/index.json", "utf-8")) as {
  entries: Record<string, { id: string; type: string }>;
};
const stories = Object.values(index.entries).filter((e) => e.type === "story");

test("there are stories to check", () => {
  expect(stories.length).toBeGreaterThan(0);
});

for (const s of stories) {
  for (const theme of ["light", "dark"]) {
    for (const locale of ["en", "zh"]) {
      test(`${s.id} · ${theme} · ${locale}`, async ({ page }) => {
        await page.goto(`/iframe.html?id=${s.id}&viewMode=story&globals=theme:${theme};locale:${locale}`);
        await page.locator("#storybook-root > *").first().waitFor();
        const r = await new AxeBuilder({ page }).include("#storybook-root").withTags(["wcag2a", "wcag2aa"]).analyze();
        expect(r.violations.flatMap((v) => v.nodes.map((n) => `${v.id} ${n.target.join(" ")}`))).toEqual([]);
      });
    }
  }
}
