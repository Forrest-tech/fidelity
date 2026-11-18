import { defineConfig, devices } from "@playwright/test";

// Every Storybook story, in both themes and both languages, must pass axe-core.
// Build first: npm run build-storybook.
const PY = process.env.PYTHON || "python";
export default defineConfig({
  testDir: "./stories-check",
  workers: 1,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:6007", ...devices["Desktop Chrome"] },
  webServer: {
    command: `"${PY}" -m http.server 6007 --bind 127.0.0.1 --directory storybook-static`,
    url: "http://127.0.0.1:6007/index.json",
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
