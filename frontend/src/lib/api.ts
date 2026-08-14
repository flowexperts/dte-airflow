/** Per-field projection with optional cast. Matches backend's `OutputField`. */
export interface OutputField {
  field: string;
  as?: string | null;
  cast?: string | null;
}

/** File-shaped output targets. Kept as plain aliases because the openapi
 *  Destination.config is flattened to `Record<string, unknown>` (JSONB). */
export interface JsonFileOutput {
  type: "json";
  path: string;
  fields?: OutputField[];
}
export interface CsvFileOutput {
  type: "csv";
  path: string;
  fields?: OutputField[];
  delimiter?: string;
  header?: boolean;
}
export interface ExcelFileOutput {
  type: "excel";
  path: string;
  fields?: OutputField[];
  sheet_name?: string;
}
export interface ParquetOutput {
  type: "parquet";
  path: string;
  fields?: OutputField[];
}

/** Output kinds the destination form can create/edit inline.
 *  Targets name a *format* only — `path` may be a local path or an
 *  object-store URI (`s3://`, `gcs://`, `az://`), so every format can
 *  address every storage backend. */
export type FileOutputTarget =
  | JsonFileOutput
  | CsvFileOutput
  | ExcelFileOutput
  | ParquetOutput;
export type FileOutputType = FileOutputTarget["type"];

export const FILE_OUTPUT_TYPES: FileOutputType[] = [
  "json",
  "csv",
  "excel",
  "parquet",
];

export const FILE_OUTPUT_EXT: Record<FileOutputType, string> = {
  json: ".json",
  csv: ".csv",
  excel: ".xlsx",
  parquet: ".parquet",
};

/**
 * Pipeline model — hand-typed because api-types.ts is stale until
 * `pnpm gen:types` regens against the new backend.
 */
export type EngineChoice =
  | "auto"
  | "duckdb"
  | "postgres"
  | "mysql"
  | "sqlite"
  | "bigquery"
  | "snowflake"
  | "trino";

// ---------- Quality contracts ----------

export type ContractType =
  | "row_count_between"
  | "column_not_null"
  | "column_unique"
  | "column_in_range"
  | "column_matches";

export interface QualityContract {
  id: string;
  type: ContractType;
  severity: "warn" | "fail";
  column?: string;
  min?: number;
  max?: number;
  regex?: string;
}

// ---------- Pipeline params ----------

/** Trigger-time typed inputs declared on a pipeline. */
export type ParamType =
  | "string"
  | "int"
  | "float"
  | "date"
  | "timestamp"
  | "boolean";

export interface PipelineParam {
  name: string;
  type: ParamType;
  required?: boolean;
  default?: string | null;
  description?: string | null;
}

export interface Pipeline {
  id: string;
  name: string;
  sources: string[];
  steps: Array<Record<string, unknown>>;
  output_id: string;
  /** Engine dispatch. "auto" (default) resolves per source composition on
   *  the backend: single-source postgres → pushdown to postgres, etc. */
  engine?: EngineChoice;
  /** Declared trigger-time inputs. Referenced from filter/map expressions
   *  as `{{params.<name>}}`; rendered as typed inputs on the trigger form. */
  params?: PipelineParam[];
  /** Quality contracts evaluated after each run (plan 044). */
  quality_contracts?: QualityContract[];
  /** Pipeline type: "transform" (default) writes output data; "quality" asserts conditions. */
  pipeline_type?: "transform" | "quality" | "eval";
}

/** Structured 4xx payloads returned by pipeline save / trigger when the
 *  engine × connection-type gate rejects. */
export interface EngineIncompatibleError {
  code: "engine_incompatible";
  engine: EngineChoice;
  incompatible_sources: Array<{
    source_id: string;
    connection_type: ConnectionType;
    reason: string;
  }>;
  incompatible_destination: null | {
    destination_id: string;
    connection_type: ConnectionType;
    reason: string;
  };
}

export interface TrinoNotEnabledError {
  code: "trino_not_enabled";
  engine: "trino";
  message: string;
}

export type PipelineGateError = EngineIncompatibleError | TrinoNotEnabledError;

export function isPipelineGateError(detail: unknown): detail is PipelineGateError {
  if (!detail || typeof detail !== "object") return false;
  const code = (detail as { code?: unknown }).code;
  return code === "engine_incompatible" || code === "trino_not_enabled";
}

/** Source model — creds live on the linked Connection, not in `config`.
 *  `format` is a top-level column on the sources table (post-migration
 *  009) so it can be queried without JSONB traversal and enforced by
 *  the extension/glob guardrail. Only meaningful for filesystem-family
 *  source_types; null = auto-detect from extension. */
export interface Source {
  /** Opaque, server-generated. Never edited after creation. */
  id: string;
  /** Editable, unique per tenant. Defaults to `id` for historic rows. */
  name?: string;
  connection_id: string;
  source_type: string;
  config: Record<string, unknown>;
  table: string;
  format?: FileFormat | null;
}

export type FileFormat = "json" | "jsonl" | "ndjson" | "csv" | "parquet" | "excel";

/** Back-compat re-export for callers still importing the old name. */
export type DltSource = Source;

export type ConnectionType =
  | "local_fs"
  | "s3" | "gcs" | "azure"
  | "postgres" | "mysql" | "sqlite"
  | "mongodb" | "rest_api"
  | "snowflake" | "bigquery";

export interface Connection {
  /** Opaque, server-generated. Never edited after creation. */
  id: string;
  /** Editable, unique per tenant. Defaults to `id` for historic rows. */
  name?: string;
  connection_type: ConnectionType;
  credentials: Record<string, unknown>;
}

export interface ProbeResult {
  ok: boolean;
  elapsed_ms: number;
  detail: string;
}

/**
 * OutputTarget discriminated union — slimmed for plan 016 (credentials
 * live on the linked Connection).
 */
export type OutputTarget =
  | JsonFileOutput
  | CsvFileOutput
  | ExcelFileOutput
  | ParquetOutput
  | { type: "postgres"; schema: string; table: string; write_disposition?: "replace" | "append" | "merge" }
  | { type: "sql_database"; dialect: "mysql" | "snowflake" | "bigquery"; schema: string; table: string; write_disposition?: "replace" | "append" | "merge" };

export interface Destination {
  /** Opaque, server-generated. Never edited after creation. */
  id: string;
  /** Editable, unique per tenant. Defaults to `id` for historic rows. */
  name?: string;
  connection_id: string;
  config: OutputTarget;
}

/** Discriminated narrowing helper — kept for callers that still special-case json. */
export function isJsonFileOutput(o: OutputTarget): o is JsonFileOutput {
  return o.type === "json";
}

/** True for any file-shaped output the destination form can edit inline. */
export function isFileOutput(o: OutputTarget): o is FileOutputTarget {
  return (FILE_OUTPUT_TYPES as string[]).includes(o.type);
}

/** Empty config for a given file output type — used when the type picker
 *  swaps the discriminant. Preserves the current `path` so users don't
 *  lose what they've typed. */
export function emptyFileOutput(
  type: FileOutputType,
  path = "",
): FileOutputTarget {
  return { type, path, fields: [] } as FileOutputTarget;
}

// Run is untyped in OpenAPI (routes return `dict`), so we model it here.
export type RunStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "failed_quality"
  | "completed_with_warnings";

export interface QualityCheckResult {
  contract_id: string;
  contract_type: string;
  label: string | null;
  passed: boolean;
  severity: "warn" | "fail";
  detail: string | null;
}

export interface RunSqlQuery {
  step_sqls?: Record<string, string>;
  final_sql?: string | null;
}

export interface Run {
  id: string;
  pipeline_id: string;
  revision_id?: string | null;
  status: RunStatus;
  error: string | null;
  rows_written: number | null;
  location: string | null;
  started_at: string | null;
  finished_at: string | null;
  /** Set when this run was fired by a schedule rather than a manual
   *  trigger (plan 047 task 4 / migration 033). Null for manual runs. */
  schedule_id?: string | null;
  /** Resolved trigger-time context: `{ params: {…}, now, today, yesterday, … }`.
   *  Only populated for runs started after plan 040 shipped. */
  params?: RunParams | null;
  /** Quality contract summary — populated after plan 044 shipped. */
  quality?: { passed: number; failed: number; warned: number } | null;
  /** Compiled SQL captured during pipeline execution. */
  sql_query?: RunSqlQuery | null;
}

/** Shape persisted in `runs.params` — matches `resolve_context` output. */
export interface RunParams {
  params: Record<string, string>;
  now: string;
  today: string;
  yesterday: string;
  start_of_week: string;
  start_of_month: string;
}

export interface SchemaField {
  name: string;
  type: string;
  children?: SchemaField[] | null;
}

export interface PreviewResponse {
  rows: Array<Record<string, unknown>>;
  count: number;
  // Plan-039 additions — compiler-produced SQL for the preview panel.
  step_sqls?: Record<string, string>;
  final_sql?: string | null;
  error?: string | null;
}

const BASE =
  typeof window === "undefined"
    ? process.env.INTERNAL_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001"
    : process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

class ApiError extends Error {
  /** Raw detail parsed from the JSON body (may be a string or an object like
   *  the structured `engine_incompatible` payload). Use `isPipelineGateError`
   *  or similar narrowers to destructure. */
  public rawDetail: unknown;

  constructor(
    public status: number,
    public detail: string,
    public url: string,
    rawDetail?: unknown,
  ) {
    super(`${status} ${detail} (${url})`);
    this.name = "ApiError";
    this.rawDetail = rawDetail ?? detail;
  }
}

export const TOKEN_STORAGE_KEY = "dte_token";
export const TOKEN_COOKIE_NAME = "dte_token";

export function readToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
  // Cookie mirror so Next middleware can gate SSR routes. SameSite=Lax
  // keeps CSRF surface small; not HttpOnly because we also need JS access.
  document.cookie = `${TOKEN_COOKIE_NAME}=${encodeURIComponent(token)}; Path=/; SameSite=Lax`;
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  document.cookie = `${TOKEN_COOKIE_NAME}=; Path=/; SameSite=Lax; Max-Age=0`;
}

async function readTokenServer(): Promise<string | null> {
  // SSR path: token isn't in localStorage — read the `dte_token` cookie the
  // login flow set (see setToken). Dynamic import so this module still bundles
  // for the client.
  const { cookies } = await import("next/headers");
  const store = await cookies();
  return store.get(TOKEN_COOKIE_NAME)?.value ?? null;
}

/** A page of results plus how many there are in total. */
export interface Page<T> {
  items: T[];
  total: number;
}

/**
 * Same request as `apiFetch`, but keeps `X-Total-Count`.
 *
 * The list endpoints return a plain array and put the total in a header, so a
 * pager that only sees the parsed body can move forward but never knows how
 * far it has to go. When the header is missing — an older backend, or a
 * response the browser can't read cross-origin — `total` falls back to the
 * page length, which degrades to "one page" rather than to a broken count.
 */
export async function apiFetchPage<T>(
  path: string,
  init?: RequestInit,
): Promise<Page<T>> {
  const { data, res } = await apiRequest<T[]>(path, init);
  const header = res.headers.get("X-Total-Count");
  const parsed = header === null ? NaN : Number(header);
  const items = data ?? [];
  return {
    items,
    total: Number.isFinite(parsed) ? parsed : items.length,
  };
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  return (await apiRequest<T>(path, init)).data;
}

async function apiRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<{ data: T; res: Response }> {
  const url = path.startsWith("http") ? path : `${BASE}${path}`;
  const token = typeof window === "undefined" ? await readTokenServer() : readToken();
  const res = await fetch(url, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    if (res.status === 401) {
      if (typeof window !== "undefined") {
        // Client-side: drop token and bounce to login.
        clearToken();
        if (!window.location.pathname.startsWith("/login")) {
          window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
        }
      } else {
        // Server-side: redirect via Next.js navigation (throws NEXT_REDIRECT).
        const { redirect } = await import("next/navigation");
        redirect("/login");
      }
    }
    let detail: unknown = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail ?? res.statusText;
    } catch {
      // non-json error
    }
    const detailStr = typeof detail === "string" ? detail : JSON.stringify(detail);
    throw new ApiError(res.status, detailStr, url, detail);
  }
  if (res.status === 204) return { data: undefined as T, res };
  return { data: (await res.json()) as T, res };
}

export interface CurrentUser {
  id: string;
  email: string;
  is_active: boolean;
  roles: string[];
  permissions: string[];
}

export async function login(email: string, password: string): Promise<string> {
  const res = await apiFetch<{ access_token: string; token_type: string }>(
    "/api/auth/login",
    { method: "POST", body: JSON.stringify({ email, password }) },
  );
  return res.access_token;
}

export async function getCurrentUser(): Promise<CurrentUser> {
  return apiFetch<CurrentUser>("/api/auth/me");
}

export { ApiError };

// ---------- Pipelines ----------

export const listPipelines = (limit = 50, offset = 0) =>
  apiFetch<Pipeline[]>(`/api/pipelines?limit=${limit}&offset=${offset}`);

export const getPipeline = (id: string) =>
  apiFetch<Pipeline>(`/api/pipelines/${encodeURIComponent(id)}`);

export const createPipeline = (pipeline: Pipeline) =>
  apiFetch<{ id: string }>(`/api/pipelines`, {
    method: "POST",
    body: JSON.stringify(pipeline),
  });

export const updatePipeline = (id: string, pipeline: Pipeline) =>
  apiFetch<{ id: string }>(`/api/pipelines/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify(pipeline),
  });

export const deletePipeline = (id: string) =>
  apiFetch<void>(`/api/pipelines/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
export const bulkDeletePipelines = (ids: string[]) =>
  apiFetch<BulkDeleteResult>(`/api/pipelines/bulk-delete`, {
    method: "POST",
    body: JSON.stringify({ ids }),
  });

export const triggerPipeline = (
  id: string,
  params: Record<string, string> = {},
) =>
  apiFetch<{ run_id: string }>(
    `/api/pipelines/${encodeURIComponent(id)}/trigger`,
    { method: "POST", body: JSON.stringify({ params }) },
  );

export const previewPipeline = (
  id: string,
  limit = 100,
  params?: Record<string, string>,
) => {
  const q = new URLSearchParams({ limit: String(limit) });
  if (params && Object.keys(params).length > 0) {
    q.set("params", JSON.stringify(params));
  }
  return apiFetch<PreviewResponse>(
    `/api/pipelines/${encodeURIComponent(id)}/preview?${q.toString()}`,
  );
};

/** Compile + sample an unsaved pipeline body (plan 038 item 6). */
export const dryRunPipeline = (
  pipeline: Pipeline,
  limit = 20,
  params?: Record<string, string>,
) => {
  const q = new URLSearchParams({ limit: String(limit) });
  if (params && Object.keys(params).length > 0) {
    q.set("params", JSON.stringify(params));
  }
  return apiFetch<PreviewResponse>(
    `/api/pipelines/dry-run?${q.toString()}`,
    { method: "POST", body: JSON.stringify(pipeline) },
  );
};

/** Per-step schema map for an unsaved pipeline body (plan 038 item 7).
 *  Keys are string-indexed step numbers to match JSON transport. */
export const pipelineStepSchemas = (pipeline: Pipeline) =>
  apiFetch<{ step_schemas: Record<string, string[]>; error: string | null }>(
    `/api/pipelines/step-schemas`,
    { method: "POST", body: JSON.stringify(pipeline) },
  );

export const listPipelineRuns = (id: string, limit = 50) =>
  apiFetch<Run[]>(
    `/api/pipelines/${encodeURIComponent(id)}/runs?limit=${limit}`,
  );

/** Paged variant — carries the total so the pager can size itself. */
export const listPipelineRunsPage = (id: string, limit: number, offset: number) =>
  apiFetchPage<Run>(
    `/api/pipelines/${encodeURIComponent(id)}/runs?limit=${limit}&offset=${offset}`,
  );

// ---------- Pipeline revisions (plan 037) ----------

export interface PipelineRevision {
  id: string;
  pipeline_id: string;
  config: Pipeline;
  changed_by: string | null;
  changed_at: string | null;
  summary: string | null;
}

export interface StepChange {
  index: number;
  kind: "added" | "removed" | "changed";
  op: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}

export interface PipelineDiff {
  name_changed: boolean;
  name_before: string | null;
  name_after: string | null;
  sources_added: string[];
  sources_removed: string[];
  output_id_changed: boolean;
  output_id_before: string | null;
  output_id_after: string | null;
  steps: StepChange[];
}

export interface RevisionDiffResponse {
  from: { id: string; changed_at: string | null; changed_by: string | null };
  to: { id: string; changed_at: string | null; changed_by: string | null };
  diff: PipelineDiff;
  summary: string;
}

export const listPipelineRevisions = (id: string, limit = 100) =>
  apiFetch<PipelineRevision[]>(
    `/api/pipelines/${encodeURIComponent(id)}/revisions?limit=${limit}`,
  );

export const listPipelineRevisionsPage = (
  id: string,
  limit: number,
  offset: number,
) =>
  apiFetchPage<PipelineRevision>(
    `/api/pipelines/${encodeURIComponent(id)}/revisions?limit=${limit}&offset=${offset}`,
  );

export const getPipelineRevision = (pipelineId: string, revisionId: string) =>
  apiFetch<PipelineRevision>(
    `/api/pipelines/${encodeURIComponent(pipelineId)}/revisions/${encodeURIComponent(revisionId)}`,
  );

export const diffPipelineRevisions = (
  pipelineId: string,
  fromId: string,
  toId: string,
) =>
  apiFetch<RevisionDiffResponse>(
    `/api/pipelines/${encodeURIComponent(pipelineId)}/diff?from=${encodeURIComponent(fromId)}&to=${encodeURIComponent(toId)}`,
  );

// ---------- Bulk delete ----------

export type BulkDeleteBlocked = { id: string; referenced_by: unknown };
export type BulkDeleteResult = {
  deleted: string[];
  not_found: string[];
  blocked: BulkDeleteBlocked[];
};

// ---------- Sources ----------

export const listSources = () => apiFetch<Source[]>(`/api/sources`);
export const getSource = (id: string) => apiFetch<Source>(`/api/sources/${encodeURIComponent(id)}`);
export const createSource = (source: Source) =>
  apiFetch<Source>(`/api/sources`, { method: "POST", body: JSON.stringify(source) });
export const updateSource = (id: string, source: Source) =>
  apiFetch<Source>(`/api/sources/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(source) });
export const deleteSource = (id: string) =>
  apiFetch<void>(`/api/sources/${encodeURIComponent(id)}`, { method: "DELETE" });
export const bulkDeleteSources = (ids: string[]) =>
  apiFetch<BulkDeleteResult>(`/api/sources/bulk-delete`, {
    method: "POST",
    body: JSON.stringify({ ids }),
  });
export const getSourceSchema = (id: string) =>
  apiFetch<{ fields: SchemaField[] }>(`/api/sources/${encodeURIComponent(id)}/schema`);

// ---------- Destinations ----------

export const listDestinations = () => apiFetch<Destination[]>(`/api/destinations`);
export const getDestination = (id: string) => apiFetch<Destination>(`/api/destinations/${encodeURIComponent(id)}`);
export const createDestination = (destination: Destination) =>
  apiFetch<Destination>(`/api/destinations`, { method: "POST", body: JSON.stringify(destination) });
export const updateDestination = (id: string, destination: Destination) =>
  apiFetch<Destination>(`/api/destinations/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(destination) });
export const deleteDestination = (id: string) =>
  apiFetch<void>(`/api/destinations/${encodeURIComponent(id)}`, { method: "DELETE" });
export const bulkDeleteDestinations = (ids: string[]) =>
  apiFetch<BulkDeleteResult>(`/api/destinations/bulk-delete`, {
    method: "POST",
    body: JSON.stringify({ ids }),
  });

// ---------- Lookup tables ----------

export interface LookupTable {
  id: string;
  name?: string | null;
  mappings: Record<string, string>;
  default?: string | null;
}

export const listLookupTables = () => apiFetch<LookupTable[]>(`/api/lookup-tables`);
export const getLookupTable = (id: string) =>
  apiFetch<LookupTable>(`/api/lookup-tables/${encodeURIComponent(id)}`);
export const createLookupTable = (lookup: LookupTable) =>
  apiFetch<LookupTable>(`/api/lookup-tables`, {
    method: "POST",
    body: JSON.stringify(lookup),
  });
export const updateLookupTable = (id: string, lookup: LookupTable) =>
  apiFetch<LookupTable>(`/api/lookup-tables/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify(lookup),
  });
export const deleteLookupTable = (id: string) =>
  apiFetch<void>(`/api/lookup-tables/${encodeURIComponent(id)}`, { method: "DELETE" });
export const bulkDeleteLookupTables = (ids: string[]) =>
  apiFetch<BulkDeleteResult>(`/api/lookup-tables/bulk-delete`, {
    method: "POST",
    body: JSON.stringify({ ids }),
  });

// ---------- Connections ----------

export const listConnections = () => apiFetch<Connection[]>(`/api/connections`);
export const getConnection = (id: string, reveal = false) =>
  apiFetch<Connection>(
    `/api/connections/${encodeURIComponent(id)}${reveal ? "?reveal=true" : ""}`,
  );
export const createConnection = (connection: Connection) =>
  apiFetch<Connection>(`/api/connections`, {
    method: "POST",
    body: JSON.stringify(connection),
  });
export const updateConnection = (id: string, connection: Connection) =>
  apiFetch<Connection>(`/api/connections/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify(connection),
  });
export const deleteConnection = (id: string) =>
  apiFetch<void>(`/api/connections/${encodeURIComponent(id)}`, { method: "DELETE" });
export const bulkDeleteConnections = (ids: string[]) =>
  apiFetch<BulkDeleteResult>(`/api/connections/bulk-delete`, {
    method: "POST",
    body: JSON.stringify({ ids }),
  });
export const testConnection = (id: string) =>
  apiFetch<ProbeResult>(`/api/connections/${encodeURIComponent(id)}/test`, {
    method: "POST",
  });

// ---------- Runs ----------

// ---------- Runs ----------

export const getRun = (id: string) =>
  apiFetch<Run>(`/api/runs/${encodeURIComponent(id)}`);

export const getRunQuality = (runId: string) =>
  apiFetch<{ results: QualityCheckResult[]; count: number }>(
    `/api/runs/${encodeURIComponent(runId)}/quality`,
  );

export const getRunOutput = (id: string, limit = 5) =>
  apiFetch<PreviewResponse>(
    `/api/runs/${encodeURIComponent(id)}/output?limit=${limit}`,
  );

export interface RunEvent {
  step_index: number;
  op: string;
  status: "started" | "completed" | "failed" | "skipped";
  message: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export const getRunEvents = (id: string) =>
  apiFetch<{ events: RunEvent[]; count: number }>(
    `/api/runs/${encodeURIComponent(id)}/events`,
  );

export const inferSchema = (source: Source) =>
  apiFetch<{ fields: SchemaField[] }>(`/api/schema/infer`, {
    method: "POST",
    body: JSON.stringify(source),
  });

// ---------- Schedules (plan 047) ----------

/** `ScheduleBase` mirror — routes return the untyped `Schedule` SQLModel
 *  as a dict, same as `Run`, so this is hand-typed rather than generated. */
export type OverlapPolicy = "skip" | "allow";

export interface Schedule {
  id: string;
  pipeline_id: string;
  cron_expr: string;
  timezone: string;
  params: Record<string, string>;
  enabled: boolean;
  overlap: OverlapPolicy;
  /** Ticker-owned bookkeeping — never client-settable. */
  next_run_at: string | null;
  last_run_id: string | null;
  last_fired_at: string | null;
  /** Required on an eval pipeline's schedule, forbidden on any other —
   *  the corpus the nightly run scores against. */
  eval_set_id: string | null;
}

/** Matches `ScheduleWriteRequest` on the backend — shared POST/PUT body. */
export interface ScheduleWriteRequest {
  id?: string;
  cron_expr: string;
  timezone: string;
  params: Record<string, string>;
  enabled: boolean;
  overlap: OverlapPolicy;
  eval_set_id?: string | null;
}

export const listSchedulesForPipeline = (pipelineId: string) =>
  apiFetch<Schedule[]>(
    `/api/pipelines/${encodeURIComponent(pipelineId)}/schedules`,
  );

export const createSchedule = (pipelineId: string, body: ScheduleWriteRequest) =>
  apiFetch<Schedule>(
    `/api/pipelines/${encodeURIComponent(pipelineId)}/schedules`,
    { method: "POST", body: JSON.stringify(body) },
  );

export const getSchedule = (id: string) =>
  apiFetch<Schedule>(`/api/schedules/${encodeURIComponent(id)}`);

export const updateSchedule = (id: string, body: ScheduleWriteRequest) =>
  apiFetch<Schedule>(`/api/schedules/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const deleteSchedule = (id: string) =>
  apiFetch<void>(`/api/schedules/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });

// ── artifacts ───────────────────────────────────────────────────────────────
//
// `GET /api/artifacts/{key}` is guarded by `run:read`, so the bytes cannot be
// reached by pointing an <embed> or pdf.js at the URL — the browser attaches
// no Authorization header to those loads. Everything here goes through fetch
// so the token rides along.

/** Strip the `artifact://` scheme rows use to reference stored blobs. */
export const artifactKey = (ref: string): string =>
  ref.replace(/^artifact:\/\//, "");

export const isArtifactRef = (v: unknown): v is string =>
  typeof v === "string" && /^artifact:\/\/[0-9a-f]{64}$/.test(v);

export function artifactUrl(key: string): string {
  return `${BASE}/api/artifacts/${encodeURIComponent(key)}`;
}

/** The `Authorization` header pdf.js should send on its range requests. */
export async function artifactAuthHeaders(): Promise<Record<string, string>> {
  const token =
    typeof window === "undefined" ? await readTokenServer() : readToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** One page of a document as the extract step cached it. */
export interface ExtractedBlock {
  text: string;
  index: number;
  page: number | null;
  bbox: { x0: number; top: number; x1: number; bottom: number } | null;
  words: { text: string; x0: number; x1: number; top: number; bottom: number }[];
  width: number | null;
  height: number | null;
}

/**
 * Blocks live under the extract step's *derived* key, not the document hash —
 * a document has as many extractions as it has step configurations. Rows
 * carry the right key in `extract_meta.key`.
 */
export async function getExtractedBlocks(key: string): Promise<ExtractedBlock[]> {
  const payload = await apiFetch<{ blocks?: ExtractedBlock[] }>(
    `/api/artifacts/${encodeURIComponent(key)}`,
  );
  return payload.blocks ?? [];
}

export const isTerminal = (status: RunStatus | undefined): boolean =>
  status === "completed" ||
  status === "failed" ||
  status === "failed_quality" ||
  status === "completed_with_warnings";

// re-export the OpenAPI namespaces for consumers wanting the raw types
export type { components, paths } from "./api-types";

// ── Evals (plan 051) ─────────────────────────────────────────────────────

export type LabelSource = "human" | "consensus" | "imported" | "judge";
export type EvalSplit = "train" | "holdout";

export interface EvalFieldSpec {
  name: string;
  type: string;
  description?: string;
  comparator?: Record<string, unknown>;
}

export interface EvalSet {
  id: string;
  name: string;
  source_id: string;
  field_specs: EvalFieldSpec[];
  labels_version: number;
  example_count?: number;
  holdout_count?: number;
  label_sources?: Record<string, number>;
  judge_labeled_warning?: string | null;
  /** Best macro-F1 among runs scored against the *current* labels. Null
   *  means never run — not zero, which is a measured failure. */
  best_macro_f1?: number | null;
  last_run_at?: string | null;
}

export interface EvalExample {
  id: string;
  eval_set_id: string;
  doc_key: string;
  doc_ref: string | null;
  labels: Record<string, unknown>;
  label_source: LabelSource;
  split: EvalSplit;
  labels_version: number | null;
}

export interface FieldMetrics {
  name: string;
  tp: number;
  fp: number;
  fn: number;
  tn: number;
  n: number;
  precision: number | null;
  recall: number | null;
  f1: number | null;
  exact_match_rate: number | null;
  null_rate: number | null;
}

export interface EvalScores {
  macro_f1: number | null;
  n: number;
  fields: FieldMetrics[];
  macro_f1_interval?: [number, number];
  holdout?: EvalScores | null;
  label_sources?: Record<string, number>;
  documents_produced?: number;
  regression?: {
    previous_run_id: string;
    previous_macro_f1: number;
    current_macro_f1: number;
    drop: number;
  } | null;
}

export interface LeaderboardEntry {
  run_id: string;
  pipeline_id: string;
  status: RunStatus;
  started_at: string | null;
  finished_at: string | null;
  config_digest: string | null;
  sweep_id: string | null;
  labels_version: number | null;
  /** Scored against labels that have since changed — shown, never ranked. */
  stale: boolean;
  macro_f1: number | null;
  macro_f1_interval?: [number, number];
  n: number;
  fields: FieldMetrics[];
  holdout?: EvalScores | null;
  regression?: EvalScores["regression"];
  rank?: number;
  tied_with_leader?: boolean;
  throughput?: Throughput | null;
}

export interface Leaderboard {
  entries: LeaderboardEntry[];
  ranking: LeaderboardEntry[];
  labels_version: number;
  judge_labeled_warning: string | null;
}

export interface FieldFailure {
  doc_key: string;
  doc_ref: string | null;
  field: string;
  expected: unknown;
  actual: unknown;
  split: EvalSplit;
}

export const listEvalSets = () => apiFetch<EvalSet[]>("/api/eval-sets");

export const getEvalSet = (id: string) =>
  apiFetch<EvalSet>(`/api/eval-sets/${encodeURIComponent(id)}`);

export const createEvalSet = (body: Partial<EvalSet>) =>
  apiFetch<EvalSet>("/api/eval-sets", { method: "POST", body: JSON.stringify(body) });

export const updateEvalSet = (id: string, body: Partial<EvalSet>) =>
  apiFetch<EvalSet>(`/api/eval-sets/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const deleteEvalSet = (id: string) =>
  apiFetch<void>(`/api/eval-sets/${encodeURIComponent(id)}`, { method: "DELETE" });

export const listEvalExamples = (id: string, opts: { split?: string; limit?: number; offset?: number } = {}) => {
  const q = new URLSearchParams();
  if (opts.split) q.set("split", opts.split);
  if (opts.limit != null) q.set("limit", String(opts.limit));
  if (opts.offset != null) q.set("offset", String(opts.offset));
  const qs = q.toString();
  return apiFetch<{ examples: EvalExample[]; total: number }>(
    `/api/eval-sets/${encodeURIComponent(id)}/examples${qs ? `?${qs}` : ""}`,
  );
};

export const upsertEvalExample = (
  id: string,
  body: {
    doc_key: string;
    doc_ref?: string | null;
    labels: Record<string, unknown>;
    label_source?: LabelSource;
    split?: EvalSplit;
  },
) =>
  apiFetch<{ example: EvalExample; labels_version: number }>(
    `/api/eval-sets/${encodeURIComponent(id)}/examples`,
    { method: "POST", body: JSON.stringify(body) },
  );

export const importEvalExamples = (
  id: string,
  body: { format: "csv" | "jsonl"; content: string; label_source?: LabelSource; split?: EvalSplit },
) =>
  apiFetch<{ imported: number; errors: { row: number; error: string }[]; labels_version: number }>(
    `/api/eval-sets/${encodeURIComponent(id)}/examples:import`,
    { method: "POST", body: JSON.stringify(body) },
  );

/** One document several variants disagreed on — the review queue's unit of
 *  work. `candidates` is per contested field, keyed by variant. */
export interface ConsensusDisagreement {
  doc_key: string;
  agreed_fields: Record<string, unknown>;
  candidates: Record<string, Record<string, unknown>>;
}

export interface BootstrapResult {
  agreed: { doc_key: string; labels: Record<string, unknown> }[];
  disagreed: ConsensusDisagreement[];
  auto_accept: boolean;
  warning: string | null;
  n_documents: number;
  written: number;
  labels_version: number;
}

/** `confirm: false` returns proposals and writes nothing. Bootstrap writes
 *  ground truth, so the preview is always the default. */
export const bootstrapEvalSet = (
  id: string,
  variantPipelineIds: string[],
  confirm = false,
) =>
  apiFetch<BootstrapResult>(`/api/eval-sets/${encodeURIComponent(id)}/bootstrap`, {
    method: "POST",
    body: JSON.stringify({ variant_pipeline_ids: variantPipelineIds, confirm }),
  });

export interface ProposeResult {
  proposals: { doc_key: string; labels: Record<string, unknown> }[];
  written: number;
  labels_version: number;
  warning: string;
}

export const proposeEvalLabels = (id: string, pipelineId: string, confirm = false) =>
  apiFetch<ProposeResult>(`/api/eval-sets/${encodeURIComponent(id)}/propose`, {
    method: "POST",
    body: JSON.stringify({ pipeline_id: pipelineId, confirm }),
  });

/** Copy a scored eval config into a shippable transform pipeline. */
export const promoteEvalPipeline = (
  id: string,
  body: { pipeline_id: string; new_pipeline_id: string; name: string; output_id: string },
) =>
  apiFetch<{ pipeline_id: string; config_digest: string }>(
    `/api/eval-sets/${encodeURIComponent(id)}/promote`,
    { method: "POST", body: JSON.stringify(body) },
  );

export const getLeaderboard = (id: string) =>
  apiFetch<Leaderboard>(`/api/eval-sets/${encodeURIComponent(id)}/leaderboard`);

export const getFieldFailures = (id: string, field: string, runId?: string) =>
  apiFetch<{ run_id: string; field: string; failures: FieldFailure[] }>(
    `/api/eval-sets/${encodeURIComponent(id)}/fields/${encodeURIComponent(field)}/failures` +
      (runId ? `?run_id=${encodeURIComponent(runId)}` : ""),
  );

/** Cost, cache-hit rate and latency for one run, measured from the rows
 *  that were actually scored. Nulls are load-bearing: an unpriced model or
 *  a run with no model calls reports null rather than a misleading zero. */
export interface Throughput {
  n_calls: number;
  cache_hit_rate: number | null;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
}

export interface SweepEstimate {
  cells: number;
  documents: number;
  uncached_calls: number;
  /** Null when no prior run has established a per-document price. */
  est_cost_usd?: number | null;
  cost_basis?: string;
  matrix: Record<string, unknown>[];
  enqueued: boolean;
  sweep_id?: string;
  /** Only present once confirmed — one real pipeline and run per cell. */
  runs?: { cell: Record<string, unknown>; pipeline_id: string; run_id: string }[];
}

export const previewSweep = (id: string, pipelineId: string, matrix: Record<string, unknown[]>) =>
  apiFetch<SweepEstimate>(`/api/eval-sets/${encodeURIComponent(id)}/sweep`, {
    method: "POST",
    body: JSON.stringify({ pipeline_id: pipelineId, matrix, confirm: false }),
  });

export const launchSweep = (id: string, pipelineId: string, matrix: Record<string, unknown[]>) =>
  apiFetch<SweepEstimate>(`/api/eval-sets/${encodeURIComponent(id)}/sweep`, {
    method: "POST",
    body: JSON.stringify({ pipeline_id: pipelineId, matrix, confirm: true }),
  });

/**
 * The eval twin of a pipeline — same steps, no destination.
 *
 * Idempotent: a second call returns the existing twin. Compare is a button
 * people press twice, and two twins would split one comparison across two
 * leaderboards.
 */
export const pipelineAsEval = (pipelineId: string) =>
  apiFetch<{ pipeline_id: string; created: boolean }>(
    `/api/pipelines/${encodeURIComponent(pipelineId)}/as-eval`,
    { method: "POST" },
  );

/**
 * The eval set a pipeline implies, derived from its structure step.
 *
 * Also idempotent, keyed on a fingerprint of field names and comparator
 * types — so two pipelines extracting the same fields from the same corpus
 * land on one set and can actually be ranked against each other.
 */
export const evalSetForPipeline = (pipelineId: string) =>
  apiFetch<{ eval_set_id: string; created: boolean; labels_version: number }>(
    `/api/eval-sets:for-pipeline`,
    { method: "POST", body: JSON.stringify({ pipeline_id: pipelineId }) },
  );

export interface ComparisonCell {
  cell_id: string;
  pipeline_id: string;
  run_id: string;
  status: string;
  error?: string | null;
  cell: Record<string, unknown>;
  documents: number;
  null_rate: number | null;
  cost_usd: number | null;
  latency_p95_ms: number | null;
  cache_hit_rate: number | null;
  /** Absent until labels exist — absent is the normal case, not an error. */
  macro_f1?: number | null;
  macro_f1_interval?: [number, number] | null;
  n?: number | null;
  rank?: number;
  tied_with_leader?: boolean;
}

export interface ComparisonField {
  name: string;
  /** Null with a single cell: agreement is undefined, not 100%. */
  agreement_rate: number | null;
  disagreement_count: number | null;
}

export interface ComparisonDocument {
  doc_key: string;
  doc_ref: string | null;
  values: Record<string, Record<string, unknown>>;
  agrees: boolean | null;
}

export interface SweepComparison {
  sweep_id: string;
  eval_set_id: string;
  labels_version: number;
  pending: number;
  cells: ComparisonCell[];
  fields: ComparisonField[];
  documents: ComparisonDocument[];
  labels: {
    total: number;
    agreed_unlabeled: number;
    /** False when every config shares a provider — bootstrap refuses the write. */
    auto_accept: boolean;
    warning: string | null;
  };
}

export interface PipelineComparison {
  sweep_id: string;
  eval_set_id: string | null;
  started_at: string | null;
  cells: number;
  pending: number;
  /** Null until labels exist — never 0, which would read as total failure. */
  best_macro_f1: number | null;
}

/**
 * Comparisons already run for a pipeline, newest first.
 *
 * Asking from a sweep variant answers for its root, and `pipeline_id` in
 * the response says which root that was.
 */
export const listPipelineComparisons = (pipelineId: string) =>
  apiFetch<{ pipeline_id: string; comparisons: PipelineComparison[] }>(
    `/api/pipelines/${encodeURIComponent(pipelineId)}/comparisons`,
  );

/** Side-by-side outputs for one sweep. Works with no labels at all. */
export const getSweepComparison = (sweepId: string) =>
  apiFetch<SweepComparison>(`/api/sweeps/${encodeURIComponent(sweepId)}/comparison`);

/** Trigger an eval pipeline against a corpus. */
export const triggerEval = (pipelineId: string, evalSetId: string) =>
  apiFetch<{ run_id: string }>(
    `/api/pipelines/${encodeURIComponent(pipelineId)}/trigger`,
    { method: "POST", body: JSON.stringify({ eval_set_id: evalSetId }) },
  );

/**
 * Two configs are indistinguishable when their confidence intervals overlap.
 * Mirrors `dte.evals.scoring.intervals_overlap` — the UI must not render a
 * ranking the backend refused to make.
 */
export const intervalsOverlap = (
  a: [number, number] | undefined,
  b: [number, number] | undefined,
): boolean => {
  if (!a || !b) return false;
  return a[0] <= b[1] && b[0] <= a[1];
};
