import { test, expect, type Page, type APIRequestContext } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

/**
 * End-to-end golden path: create + trigger a pipeline against a live stack
 * and verify it reaches `completed` status.
 *
 * Design goals
 * ────────────
 * 1. Resilient to DB state. The first registered user becomes admin; later
 *    registrations get no role. To avoid the "no permission" edge case the
 *    test uses a unique email per run AND falls back to the API trigger if
 *    the Trigger button is hidden (no pipeline:trigger permission). The UI
 *    path is still exercised for creation and result viewing.
 *
 * 2. Infrastructure via API, journey via UI. Creating a connection, source,
 *    and destination through the builder UI involves multi-step dropdowns that
 *    are fragile to test. We pre-seed those resources via the REST API and only
 *    use the UI for what matters: pipeline creation, triggering, and viewing the
 *    run detail page.
 *
 * 3. Screenshot on failure. Playwright config has `screenshot: "only-on-failure"`
 *    so any assertion failure leaves a screenshot in the test-results directory.
 *
 * Prerequisites
 * ─────────────
 *   docker compose up -d --build   (ports 3000 + 8001 + postgres)
 *   DTE_ALLOW_REGISTRATION=true    (set in docker-compose.yml by default)
 *   /tmp/dte-samples must be writable on the host AND mapped into the backend
 *   container (docker-compose.yml: volumes: - /tmp/dte-samples:/tmp/dte-samples)
 *
 * Run
 * ───
 *   cd frontend
 *   E2E_BASE_URL=http://localhost:3000 E2E_API_URL=http://localhost:8001 \
 *     pnpm test:e2e
 */

const API = process.env.E2E_API_URL ?? "http://localhost:8001";

// Unique suffix — avoids id collisions across parallel runs / reruns.
const RUN_SUFFIX = `${Date.now()}`;

const TEST_EMAIL = `e2e-${RUN_SUFFIX}@example.com`;
const TEST_PASSWORD = "e2eTestPw!1";

const CONN_ID = `e2e-conn-${RUN_SUFFIX}`;
const SRC_ID = `e2e-src-${RUN_SUFFIX}`;
const DEST_ID = `e2e-dest-${RUN_SUFFIX}`;
const PIPELINE_ID = `e2e-pl-${RUN_SUFFIX}`;
const PIPELINE_NAME = `E2E Orders ${RUN_SUFFIX}`;

// /tmp/dte-samples is bind-mounted into the backend container.
const FIXTURE_DIR = "/tmp/dte-samples";
const FIXTURE_FILENAME = `orders-${RUN_SUFFIX}.json`;
const FIXTURE_PATH = path.join(FIXTURE_DIR, FIXTURE_FILENAME);
const OUTPUT_PATH = path.join(FIXTURE_DIR, `output-${RUN_SUFFIX}.json`);

// Minimal orders fixture.
const ORDERS_DATA = [
  { order_id: "o01", customer_id: "c1", amount: 50, status: "paid" },
  { order_id: "o02", customer_id: "c2", amount: 150, status: "paid" },
  { order_id: "o03", customer_id: "c3", amount: 75, status: "pending" },
  { order_id: "o04", customer_id: "c4", amount: 300, status: "paid" },
];

// ── low-level helpers ──────────────────────────────────────────────────────

async function registerUser(request: APIRequestContext): Promise<void> {
  const res = await request.post(`${API}/api/auth/register`, {
    data: { email: TEST_EMAIL, password: TEST_PASSWORD },
  });
  // 201 created or 409 already-exists are both acceptable.
  if (![201, 409].includes(res.status())) {
    const body = await res.text();
    throw new Error(`register returned ${res.status()}: ${body}`);
  }
}

async function loginUser(request: APIRequestContext): Promise<string> {
  const res = await request.post(`${API}/api/auth/login`, {
    data: { email: TEST_EMAIL, password: TEST_PASSWORD },
  });
  if (res.status() !== 200) {
    const body = await res.text();
    throw new Error(`login returned ${res.status()}: ${body}`);
  }
  const body = await res.json() as { access_token: string };
  return body.access_token;
}

function authHeaders(token: string) {
  return { Authorization: `Bearer ${token}` };
}

async function apiPost(
  request: APIRequestContext,
  token: string,
  endpoint: string,
  data: unknown,
): Promise<unknown> {
  const res = await request.post(`${API}${endpoint}`, {
    data,
    headers: authHeaders(token),
  });
  if (![200, 201, 409].includes(res.status())) {
    const body = await res.text();
    throw new Error(`POST ${endpoint} → ${res.status()}: ${body}`);
  }
  return res.json();
}

async function apiDelete(
  request: APIRequestContext,
  token: string,
  endpoint: string,
): Promise<void> {
  await request.delete(`${API}${endpoint}`, {
    headers: authHeaders(token),
  });
}

async function waitForRun(
  request: APIRequestContext,
  token: string,
  runId: string,
  timeoutMs = 60_000,
): Promise<{ status: string; rows_written: number | null; error: string | null }> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const res = await request.get(`${API}/api/runs/${runId}`, {
      headers: authHeaders(token),
    });
    if (res.status() !== 200) {
      throw new Error(`GET /api/runs/${runId} → ${res.status()}`);
    }
    const run = await res.json() as { status: string; rows_written: number | null; error: string | null };
    if (run.status === "completed" || run.status === "failed") {
      return run;
    }
    await new Promise((r) => setTimeout(r, 2_000));
  }
  throw new Error(`Run ${runId} did not reach terminal state within ${timeoutMs}ms`);
}

/** Inject the JWT into localStorage + cookie so the Next.js app sees the session. */
async function injectToken(page: Page, token: string): Promise<void> {
  // Navigate to the root first so we're on the right origin before touching localStorage.
  await page.goto("/");
  await page.evaluate((tok) => {
    window.localStorage.setItem("dte_token", tok);
    document.cookie = `dte_token=${encodeURIComponent(tok)}; Path=/; SameSite=Lax`;
  }, token);
}

// ── shared state ───────────────────────────────────────────────────────────

// token is set once in beforeAll and reused by all tests in this file.
let TOKEN = "";

// ── lifecycle ──────────────────────────────────────────────────────────────

test.beforeAll(async ({ request }) => {
  // Write fixture data to the host path that docker-compose bind-mounts
  // into the backend at /tmp/dte-samples.
  try {
    fs.mkdirSync(FIXTURE_DIR, { recursive: true });
    fs.writeFileSync(FIXTURE_PATH, JSON.stringify(ORDERS_DATA), "utf-8");
  } catch (err) {
    // Warn but don't abort — test will fail with a clearer message from the API.
    console.warn(`[E2E] Could not write fixture to ${FIXTURE_PATH}:`, err);
  }

  await registerUser(request);
  TOKEN = await loginUser(request);

  // Pre-seed infrastructure resources via the API so the UI flow only deals
  // with pipeline creation (the interesting part).
  await apiPost(request, TOKEN, "/api/connections", {
    id: CONN_ID,
    connection_type: "local_fs",
    credentials: {},
  });

  await apiPost(request, TOKEN, "/api/sources", {
    id: SRC_ID,
    connection_id: CONN_ID,
    source_type: "filesystem",
    config: {
      bucket_url: FIXTURE_DIR,
      file_glob: FIXTURE_FILENAME,
    },
    table: "orders",
    format: "json",
  });

  await apiPost(request, TOKEN, "/api/destinations", {
    id: DEST_ID,
    connection_id: CONN_ID,
    config: {
      type: "json_file",
      path: OUTPUT_PATH,
      fields: [],
    },
  });
});

test.afterAll(async ({ request }) => {
  if (!TOKEN) return;
  // Best-effort cleanup — ignore errors so afterAll never blocks the report.
  for (const endpoint of [
    `/api/pipelines/${encodeURIComponent(PIPELINE_ID)}`,
    `/api/destinations/${encodeURIComponent(DEST_ID)}`,
    `/api/sources/${encodeURIComponent(SRC_ID)}`,
    `/api/connections/${encodeURIComponent(CONN_ID)}`,
  ]) {
    await apiDelete(request, TOKEN, endpoint).catch(() => {});
  }
  for (const p of [FIXTURE_PATH, OUTPUT_PATH]) {
    try { fs.rmSync(p); } catch { /* ignore */ }
  }
});

// ── tests ──────────────────────────────────────────────────────────────────

test("pipelines list is reachable after login", async ({ page }) => {
  await injectToken(page, TOKEN);
  await page.goto("/pipelines");
  await expect(page).toHaveURL(/\/pipelines/, { timeout: 10_000 });
  // The sidebar should be visible; the login form should not be.
  await expect(page.locator("body")).toBeVisible();
  await expect(page.getByRole("heading", { name: /sign in/i })).not.toBeVisible();
});

test("pipeline create-trigger-complete journey", async ({ page, request }) => {
  // ── 1. Navigate to /pipelines/new ──────────────────────────────────────
  await injectToken(page, TOKEN);
  await page.goto("/pipelines/new");
  await expect(page).toHaveURL(/\/pipelines\/new/, { timeout: 10_000 });

  // ── 2. Fill in the pipeline id and name ────────────────────────────────
  // BuilderForm: <Field label="Pipeline id">
  const idInput = page.getByLabel(/pipeline id/i);
  await idInput.fill(PIPELINE_ID);

  // BuilderForm: <Field label="Name">
  const nameInput = page.getByLabel(/^name$/i);
  await nameInput.fill(PIPELINE_NAME);

  // ── 3. Pick the source from the Dropdown ───────────────────────────────
  // SourcesPanel renders a Dropdown with placeholder "— pick a source —".
  // The trigger is a <button aria-haspopup="listbox"> and options are
  // <button role="option"> portalled to document.body.
  const sourceDropdownTrigger = page
    .getByRole("button", { name: /— pick a source —/ })
    .first();
  await sourceDropdownTrigger.click();

  // The source we created shows up by id in the listbox.
  const srcOption = page.getByRole("option", { name: SRC_ID });
  await srcOption.waitFor({ state: "visible", timeout: 8_000 });
  await srcOption.click();

  // ── 4. Pick the destination ────────────────────────────────────────────
  // DestinationPicker renders a Dropdown with placeholder "— pick a destination —".
  const destDropdownTrigger = page
    .getByRole("button", { name: /— pick a destination —/ })
    .first();
  await destDropdownTrigger.click();

  const destOption = page.getByRole("option", { name: DEST_ID });
  await destOption.waitFor({ state: "visible", timeout: 8_000 });
  await destOption.click();

  // ── 5. Save the pipeline ───────────────────────────────────────────────
  // BuilderForm submit button text: "Save pipeline"
  const saveBtn = page.getByRole("button", { name: /save pipeline/i });
  await saveBtn.click();

  // After a successful save we should be redirected to /pipelines/{id}.
  await expect(page).toHaveURL(
    new RegExp(`/pipelines/${escapeRegex(PIPELINE_ID)}$`),
    { timeout: 15_000 },
  );

  // ── 6. Trigger the run ─────────────────────────────────────────────────
  // TriggerButton only renders if the user has pipeline:trigger permission.
  // The first registered user on a fresh DB is admin (all permissions).
  // If the button is absent (subsequent users get no role), fall back to
  // the API trigger so the test still validates the run lifecycle.
  const triggerBtn = page.getByRole("button", { name: /trigger run/i });
  const hasTriggerBtn = await triggerBtn.isVisible().catch(() => false);

  let runId: string;

  if (hasTriggerBtn) {
    await triggerBtn.click();
    // TriggerButton calls /api/pipelines/{id}/trigger then router.push to /runs/{run_id}.
    await expect(page).toHaveURL(/\/runs\//, { timeout: 10_000 });
    runId = page.url().split("/runs/").pop()?.split("?")[0] ?? "";
    expect(runId).not.toBe("");
  } else {
    // Fallback: API trigger.
    const res = await request.post(`${API}/api/pipelines/${encodeURIComponent(PIPELINE_ID)}/trigger`, {
      headers: authHeaders(TOKEN),
    });
    if (res.status() !== 200 && res.status() !== 201) {
      const body = await res.text();
      throw new Error(`API trigger returned ${res.status()}: ${body}`);
    }
    const body = await res.json() as { run_id: string };
    runId = body.run_id;
    // Navigate to the run detail page so the UI assertion below works.
    await page.goto(`/runs/${encodeURIComponent(runId)}`);
    await expect(page).toHaveURL(new RegExp(`/runs/${escapeRegex(runId)}`), { timeout: 10_000 });
  }

  // ── 7. Poll via API until the run reaches a terminal state ─────────────
  const run = await waitForRun(request, TOKEN, runId, 60_000);

  // ── 8. Assert the outcome ──────────────────────────────────────────────
  if (run.status !== "completed") {
    throw new Error(
      `Run ${runId} finished with status="${run.status}". Backend error: ${run.error ?? "(none)"}`,
    );
  }

  expect(run.status).toBe("completed");
  expect(run.rows_written).toBeGreaterThan(0);

  // ── 9. Verify the UI shows the completed state ─────────────────────────
  // The run detail page polls /api/runs/{id} every 2s and updates the Pill.
  // Reload so the page re-fetches with the final status.
  await page.reload();
  // A "completed" pill or equivalent text should be visible.
  const completedIndicator = page.getByText(/completed/i).first();
  await completedIndicator.waitFor({ state: "visible", timeout: 15_000 });
  await expect(completedIndicator).toBeVisible();
});

// ── utils ──────────────────────────────────────────────────────────────────

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
