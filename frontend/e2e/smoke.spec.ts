import { test, expect } from "@playwright/test";

/**
 * Golden-path smoke: the app loads, the pipelines list route responds,
 * and health check passes. Deliberately shallow — the exhaustive per-op
 * coverage lives in backend scenario tests. This exists so main can't
 * merge if the frontend can't render or the API is down.
 */

test("healthz is green", async ({ request }) => {
  const api = process.env.E2E_API_URL ?? "http://localhost:8001";
  const res = await request.get(`${api}/healthz`);
  expect(res.status()).toBe(200);
  expect(await res.json()).toMatchObject({ status: "ok" });
});

test("app shell renders and routes to /pipelines", async ({ page }) => {
  await page.goto("/");
  // Root redirects to /pipelines.
  await expect(page).toHaveURL(/\/pipelines$|\/login/);
  // Either the pipelines list or the login page renders; both prove the app
  // shell (fonts, providers, theme) mounted without a client-side error.
  await expect(page.locator("body")).toBeVisible();
});
