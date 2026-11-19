/// <reference types="vitest" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Dev server on 5173, API proxied to the backend on 8000 (same origin for cookies).
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": { target: process.env.FIDELITY_API || "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  build: { outDir: "dist", sourcemap: false },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"], // e2e/ belongs to Playwright
    css: false,
    testTimeout: 15_000, // jsdom page tests are slow on small machines; avoids false failures
  },
});
