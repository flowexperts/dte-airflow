import { test, expect, type Page } from "@playwright/test";

/**
 * Golden-path smoke against the compose stack: DTE renders natively inside
 * Airflow (plan 066) — no iframe — and takes Airflow's theme and fonts.
 */
const BASE = process.env.E2E_BASE_URL ?? "http://localhost:8080";

async function login(page: Page) {
  await page.goto(`${BASE}/`);
  await page.getByLabel(/username/i).fill("admin");
  await page.getByLabel(/password/i).fill("admin");
  await page.getByRole("button", { name: /sign in|log in|login/i }).click();
  await page.waitForURL((u) => !u.pathname.includes("login"));
}

test("DTE renders inside Airflow with Airflow's theme", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page);
  await page.goto(`${BASE}/plugin/dte`);
  await expect(page).toHaveURL(/\/plugin\/dte\/pipelines$/);
  const root = page.locator(".dte-root");
  await expect(root).toBeVisible();
  expect(await page.locator("iframe").count()).toBe(0);

  const style = await root.evaluate((el) => {
    const cs = getComputedStyle(el);
    const body = getComputedStyle(document.body);
    return { font: cs.fontFamily, bodyFont: body.fontFamily, text: cs.color, bg: cs.getPropertyValue("--bg").trim() };
  });
  expect(style.font).toContain("Inter");
  expect(style.bg).not.toBe("");
  expect(errors).toEqual([]);
});

test("Admin entry opens the sources section", async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/plugin/dte-sources`);
  await expect(page).toHaveURL(/\/plugin\/dte-sources\/sources$/);
  await expect(page.locator(".dte-root")).toBeVisible();
});
