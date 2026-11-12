import { defineConfig, devices } from "@playwright/test";

/**
 * E2E against a running fixture-backed stack (demo data from `manage.py seed_demo`; no vendor data).
 * Default target is the Vite dev server (which proxies /api to Django). Set E2E_BASE_URL to target the
 * Compose proxy instead, e.g. http://127.0.0.1:8080.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:5173",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
