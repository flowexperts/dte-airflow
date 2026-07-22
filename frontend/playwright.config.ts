import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for DTE smoke tests.
 *
 * Assumes the full stack (backend + frontend + postgres) is up:
 *   docker compose up -d --build
 *
 * CI provisions those services in a `services:` block before running.
 * Locally: `pnpm --dir frontend test:e2e:install && pnpm --dir frontend test:e2e`.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});
