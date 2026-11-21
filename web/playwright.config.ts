import { defineConfig, devices } from "@playwright/test";

// Runs the real backend (throw-away SQLite database, seeded users) serving the built web app.
// Build first: npm run build. PYTHON can point at the project's virtual environment.
const PY = process.env.PYTHON || "python";
const PORT = 8765;
const DB = "sqlite+aiosqlite:///./.e2e/e2e.db";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  // Visual baselines are created in CI on Linux (spec section 9); locally missing ones are written, not compared.
  updateSnapshots: "missing",
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "retain-on-failure" },
  webServer: {
    command: `"${PY}" scripts/e2e_seed.py && "${PY}" -m uvicorn app.main:app --port ${PORT}`,
    cwd: "../backend",
    url: `http://127.0.0.1:${PORT}/api/v1/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    env: { FIDELITY_DB_URL: DB, FIDELITY_WEB_DIST: process.env.FIDELITY_WEB_DIST ?? "", FIDELITY_SECRET: "e2e-secret-e2e-secret-e2e-secret-1234", QA_SERVER_PORT: String(PORT), PYTHONUTF8: "1" },
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } },
    { name: "tablet", use: { ...devices["Desktop Chrome"], viewport: { width: 768, height: 1024 } } },
    { name: "phone", use: { ...devices["Desktop Chrome"], viewport: { width: 375, height: 812 } } },
  ],
});
