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
export type FileOutputTarget = JsonFileOutput | CsvFileOutput | ExcelFileOutput | ParquetOutput;
export type FileOutputType = FileOutputTarget["type"];

export const FILE_OUTPUT_TYPES: FileOutputType[] = ["json", "csv", "excel", "parquet"];

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
  | "mssql"
  | "sqlite"
  | "bigquery"
  | "snowflake"
  | "trino";

// ---------- Quality contracts ----------

export type ContractType =
  "row_count_between" | "column_not_null" | "column_unique" | "column_in_range" | "column_matches";

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
export type ParamType = "string" | "int" | "float" | "date" | "timestamp" | "boolean";

export interface PipelineParam {
  name: string;
  type: ParamType;
  required?: boolean;
  default?: string | null;
  description?: string | null;
}

/**
 * One use of a `Source` within a pipeline. `alias` is the compiler
 * registry key — it replaces the bare source id, which is what lets the
 * same `sql_database` Source be picked more than once (against different
 * tables) in one pipeline. `table` is required when the resolved source
 * is `sql_database` and forbidden for every other kind. `alias` is never
 * defaulted server-side — the builder fills it in when a table is picked.
 */
export interface SourceTableRef {
  source_id: string;
  table?: string | null;
  alias: string;
}

export interface Pipeline {
  id: string;
  name: string;
  sources: SourceTableRef[];
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
  /** Pipeline type: "transform" (default) writes output data; "quality"
   *  asserts conditions; "eval" scores extraction against labels; "viz"
   *  feeds a dashboard tile and writes nowhere (plan 064). */
  pipeline_type?: "transform" | "quality" | "eval" | "viz";
  /**
   * The comparison this eval pipeline expands to: dotted axis path → values
   * to vary (plan 055). Eval pipelines only — the API 422s a matrix on any
   * other type rather than storing one that would silently do nothing.
   *
   * `null`/absent is N=1: the config as it stands, run once. That is the
   * nightly regression check, not an empty comparison.
   */
  matrix?: Record<string, string[]> | null;
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
  | "s3"
  | "gcs"
  | "azure"
  | "sftp"
  | "postgres"
  | "mysql"
  | "mssql"
  | "sqlite"
  | "mongodb"
  | "rest_api"
  | "snowflake"
  | "bigquery";

/** What this deployment can read and write, from the Airflow providers
 *  installed alongside DTE (`GET /api/capabilities`, plan 074). */
export interface Capabilities {
  connection_kinds: Record<ConnectionType, { available: boolean; install: string | null }>;
  source_kinds: Record<string, boolean>;
  destination_types: Record<string, boolean>;
}

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
  | {
      type: "postgres";
      schema: string;
      table: string;
      write_disposition?: "replace" | "append" | "merge";
    }
  | {
      type: "sql_database";
      dialect: "mysql" | "mssql" | "snowflake" | "bigquery";
      schema: string;
      table: string;
      write_disposition?: "replace" | "append" | "merge";
    };

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
export function emptyFileOutput(type: FileOutputType, path = ""): FileOutputTarget {
  return { type, path, fields: [] } as FileOutputTarget;
}

// Run is untyped in OpenAPI (routes return `dict`), so we model it here.
export type RunStatus =
  "pending" | "running" | "completed" | "failed" | "failed_quality" | "completed_with_warnings";

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
  /** True when Airflow fired this run on the pipeline's schedule rather
   *  than a manual trigger (dag_run.run_type, plan 068). */
  scheduled?: boolean;
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

// The DTE API is mounted by the Airflow plugin at /dte, same origin as this
// UI (/dte/ui), so Airflow's own session cookie authenticates every call.
const BASE = "/dte";

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
export async function apiFetchPage<T>(path: string, init?: RequestInit): Promise<Page<T>> {
  const { data, res } = await apiRequest<T[]>(path, init);
  const header = res.headers.get("X-Total-Count");
  const parsed = header === null ? NaN : Number(header);
  const items = data ?? [];
  return {
    items,
    total: Number.isFinite(parsed) ? parsed : items.length,
  };
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  return (await apiRequest<T>(path, init)).data;
}

async function apiRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<{ data: T; res: Response }> {
  const url = path.startsWith("http") ? path : `${BASE}${path}`;
  const res = await fetch(url, {
    ...init,
    credentials: "same-origin",
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    // Session gone: Airflow owns login, so send the whole window there.
    if (res.status === 401 && typeof window !== "undefined") {
      window.top!.location.href = "/";
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

export async function getCurrentUser(): Promise<CurrentUser> {
  return apiFetch<CurrentUser>("/api/me");
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

/** Omits `schedule` and `notifications`: each is owned by its own route, the
 *  server keeps it when absent, and the caller's copy may predate an edit. */
export const updatePipeline = (id: string, pipeline: Pipeline) => {
  const body: Record<string, unknown> = { ...pipeline };
  delete body.schedule;
  delete body.notifications;
  return apiFetch<{ id: string }>(`/api/pipelines/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
};

export const deletePipeline = (id: string) =>
  apiFetch<void>(`/api/pipelines/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
export const bulkDeletePipelines = (ids: string[]) =>
  apiFetch<BulkDeleteResult>(`/api/pipelines/bulk-delete`, {
    method: "POST",
    body: JSON.stringify({ ids }),
  });

export const triggerPipeline = (id: string, params: Record<string, string> = {}) =>
  apiFetch<{ run_id: string }>(`/api/pipelines/${encodeURIComponent(id)}/trigger`, {
    method: "POST",
    body: JSON.stringify({ params }),
  });

export const previewPipeline = (id: string, limit = 100, params?: Record<string, string>) => {
  const q = new URLSearchParams({ limit: String(limit) });
  if (params && Object.keys(params).length > 0) {
    q.set("params", JSON.stringify(params));
  }
  return apiFetch<PreviewResponse>(
    `/api/pipelines/${encodeURIComponent(id)}/preview?${q.toString()}`,
  );
};

/** Compile + sample an unsaved pipeline body (plan 038 item 6). */
export const dryRunPipeline = (pipeline: Pipeline, limit = 20, params?: Record<string, string>) => {
  const q = new URLSearchParams({ limit: String(limit) });
  if (params && Object.keys(params).length > 0) {
    q.set("params", JSON.stringify(params));
  }
  return apiFetch<PreviewResponse>(`/api/pipelines/dry-run?${q.toString()}`, {
    method: "POST",
    body: JSON.stringify(pipeline),
  });
};

/** Per-step schema map for an unsaved pipeline body (plan 038 item 7),
 *  plus dialect feedback for raw-SQL steps (plan 062). Keys are
 *  string-indexed step numbers to match JSON transport. */
export interface StepSchemasResponse {
  step_schemas: Record<string, string[]>;
  error: string | null;
  /** Index of the step that failed to compile, if any. */
  error_step: number | null;
  /** The dialect the pipeline's tables execute on ("duckdb", "postgres", …). */
  dialect: string;
  /** Per step: the raw-SQL fragment as the target dialect receives it.
   *  Absent when the target gets exactly what the user typed. */
  step_expr_sql: Record<string, string>;
  warnings: { step: number; code: string; message: string }[];
}

export const pipelineStepSchemas = (pipeline: Pipeline) =>
  apiFetch<StepSchemasResponse>(`/api/pipelines/step-schemas`, {
    method: "POST",
    body: JSON.stringify(pipeline),
  });

export const listPipelineRuns = (id: string, limit = 50) =>
  apiFetch<Run[]>(`/api/pipelines/${encodeURIComponent(id)}/runs?limit=${limit}`);

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
  apiFetch<PipelineRevision[]>(`/api/pipelines/${encodeURIComponent(id)}/revisions?limit=${limit}`);

export const listPipelineRevisionsPage = (id: string, limit: number, offset: number) =>
  apiFetchPage<PipelineRevision>(
    `/api/pipelines/${encodeURIComponent(id)}/revisions?limit=${limit}&offset=${offset}`,
  );

export const getPipelineRevision = (pipelineId: string, revisionId: string) =>
  apiFetch<PipelineRevision>(
    `/api/pipelines/${encodeURIComponent(pipelineId)}/revisions/${encodeURIComponent(revisionId)}`,
  );

export const diffPipelineRevisions = (pipelineId: string, fromId: string, toId: string) =>
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
  apiFetch<Source>(`/api/sources/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify(source),
  });
export const deleteSource = (id: string) =>
  apiFetch<void>(`/api/sources/${encodeURIComponent(id)}`, { method: "DELETE" });
export const bulkDeleteSources = (ids: string[]) =>
  apiFetch<BulkDeleteResult>(`/api/sources/bulk-delete`, {
    method: "POST",
    body: JSON.stringify({ ids }),
  });
export const getSourceSchema = (id: string, table?: string | null) =>
  apiFetch<{ fields: SchemaField[] }>(
    `/api/sources/${encodeURIComponent(id)}/schema${table ? `?table=${encodeURIComponent(table)}` : ""}`,
  );

/** Tables visible through a `sql_database` source's connection, respecting
 *  its configured schema if any. 422 for non-`sql_database` sources. */
export const listSourceTables = (id: string) =>
  apiFetch<{ tables: string[] }>(`/api/sources/${encodeURIComponent(id)}/tables`);

// ---------- Destinations ----------

export const listDestinations = () => apiFetch<Destination[]>(`/api/destinations`);
export const getDestination = (id: string) =>
  apiFetch<Destination>(`/api/destinations/${encodeURIComponent(id)}`);
export const createDestination = (destination: Destination) =>
  apiFetch<Destination>(`/api/destinations`, { method: "POST", body: JSON.stringify(destination) });
export const updateDestination = (id: string, destination: Destination) =>
  apiFetch<Destination>(`/api/destinations/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify(destination),
  });
export const deleteDestination = (id: string) =>
  apiFetch<void>(`/api/destinations/${encodeURIComponent(id)}`, { method: "DELETE" });
/** Columns of a DB destination's target table. 422 for file targets —
 *  their shape is whatever the pipeline writes, so there is nothing to read. */
export const getDestinationSchema = (id: string) =>
  apiFetch<{ fields: SchemaField[] }>(`/api/destinations/${encodeURIComponent(id)}/schema`);

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
  apiFetch<Connection>(`/api/connections/${encodeURIComponent(id)}${reveal ? "?reveal=true" : ""}`);
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

/** Schema/database names visible through a connection's native ibis
 *  backend. 422 for connection types with no native backend (e.g.
 *  filesystem-family) or a real driver failure. */
export const listConnectionSchemas = (id: string) =>
  apiFetch<{ schemas: string[] }>(`/api/connections/${encodeURIComponent(id)}/schemas`);

// ---------- Runs ----------

// ---------- Runs ----------

export const getRun = (id: string) => apiFetch<Run>(`/api/runs/${encodeURIComponent(id)}`);

export const getRunQuality = (runId: string) =>
  apiFetch<{ results: QualityCheckResult[]; count: number }>(
    `/api/runs/${encodeURIComponent(runId)}/quality`,
  );

export const getRunOutput = (id: string, limit = 5) =>
  apiFetch<PreviewResponse>(`/api/runs/${encodeURIComponent(id)}/output?limit=${limit}`);

export interface RunEvent {
  step_index: number;
  op: string;
  status: "started" | "completed" | "failed" | "skipped";
  message: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export const getRunEvents = (id: string) =>
  apiFetch<{ events: RunEvent[]; count: number }>(`/api/runs/${encodeURIComponent(id)}/events`);

export const inferSchema = (source: Source, table?: string | null) =>
  apiFetch<{ fields: SchemaField[] }>(
    `/api/schema/infer${table ? `?table=${encodeURIComponent(table)}` : ""}`,
    {
      method: "POST",
      body: JSON.stringify(source),
    },
  );

// ---------- Notifications (plan 070) ----------

export type NotifyEvent = "failure" | "success" | "retry";

/** Any notifier an installed Airflow provider registers, fired on run events
 *  (manual and scheduled). `params` are its constructor kwargs. */
export interface PipelineNotification {
  notifier: string;
  params: Record<string, unknown>;
  on: NotifyEvent[];
}

export interface NotifierInfo {
  notifier: string;
  name: string;
  doc: string;
  params: { name: string; required: boolean; default: string | null }[];
}

export const listNotifiers = () => apiFetch<NotifierInfo[]>("/api/notifiers");

const notificationsPath = (pipelineId: string) =>
  `/api/pipelines/${encodeURIComponent(pipelineId)}/notifications`;

export const getNotifications = (pipelineId: string) =>
  apiFetch<PipelineNotification[]>(notificationsPath(pipelineId));

export const putNotifications = (pipelineId: string, body: PipelineNotification[]) =>
  apiFetch<PipelineNotification[]>(notificationsPath(pipelineId), {
    method: "PUT",
    body: JSON.stringify(body),
  });

// ---------- Schedule (plan 068) ----------

/** A pipeline's one schedule — `PipelineSchedule` plus the computed
 *  `next_run_at`. Part of the pipeline spec: every change is a revision,
 *  and a revision is the Airflow DAG version. */
export type OverlapPolicy = "skip" | "allow";

/** `assets` (plan 089) fires after the chosen upstream pipelines write their
 *  outputs; a schedule saved before modes existed reads as `cron`. */
export type ScheduleTrigger = "cron" | "assets";

export interface Schedule {
  mode: ScheduleTrigger;
  cron_expr: string | null;
  /** Upstream output Asset URIs, from `listAssets`. */
  assets: string[];
  timezone: string;
  params: Record<string, string>;
  enabled: boolean;
  overlap: OverlapPolicy;
  /** Required on an eval pipeline's schedule, forbidden on any other —
   *  the corpus the nightly run scores against. */
  eval_set_id: string | null;
  /** On failure (plan 070). Retries are refused on append destinations. */
  retries: number;
  retry_delay_s: number;
  timeout_s: number | null;
  next_run_at: string | null;
}

/** Matches `PipelineSchedule` on the backend — the PUT body. */
export interface ScheduleWriteRequest {
  mode: ScheduleTrigger;
  cron_expr: string | null;
  assets: string[];
  timezone: string;
  params: Record<string, string>;
  enabled: boolean;
  overlap: OverlapPolicy;
  eval_set_id?: string | null;
  retries: number;
  retry_delay_s: number;
  timeout_s: number | null;
}

const schedulePath = (pipelineId: string) =>
  `/api/pipelines/${encodeURIComponent(pipelineId)}/schedule`;

export const getSchedule = (pipelineId: string) =>
  apiFetch<Schedule | null>(schedulePath(pipelineId));

export const putSchedule = (pipelineId: string, body: ScheduleWriteRequest) =>
  apiFetch<Schedule>(schedulePath(pipelineId), { method: "PUT", body: JSON.stringify(body) });

export const deleteSchedule = (pipelineId: string) =>
  apiFetch<void>(schedulePath(pipelineId), { method: "DELETE" });

/** One transform pipeline's output Airflow Asset (plan 089). */
export interface PipelineAsset {
  pipeline_id: string;
  pipeline_name: string;
  uri: string;
}

export const listAssets = () => apiFetch<PipelineAsset[]>("/api/assets");

// ── artifacts ───────────────────────────────────────────────────────────────
//
// `GET /api/artifacts/{key}` is guarded by `run:read`, so the bytes cannot be
// reached by pointing an <embed> or pdf.js at the URL — the browser attaches
// no Authorization header to those loads. Everything here goes through fetch
// so the token rides along.

/** Strip the `artifact://` scheme rows use to reference stored blobs. */
export const artifactKey = (ref: string): string => ref.replace(/^artifact:\/\//, "");

export const isArtifactRef = (v: unknown): v is string =>
  typeof v === "string" && /^artifact:\/\/[0-9a-f]{64}$/.test(v);

export function artifactUrl(key: string): string {
  return `${BASE}/api/artifacts/${encodeURIComponent(key)}`;
}

/** Extra headers for pdf.js range requests. None: the Airflow session cookie
 *  rides along on same-origin requests. */
export async function artifactAuthHeaders(): Promise<Record<string, string>> {
  return {};
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

export const listEvalExamples = (
  id: string,
  opts: { split?: string; limit?: number; offset?: number } = {},
) => {
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
export const bootstrapEvalSet = (id: string, variantPipelineIds: string[], confirm = false) =>
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
  /**
   * Combinations removed before running, each with a reason — a cell count
   * smaller than the product you built must never be silent.
   */
  dropped?: { cell: Record<string, unknown>; reason: string }[];
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
  /** Rows whose provider call failed. A null is a finding; an error is not. */
  error_count: number;
  error_sample: string | null;
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
  /**
   * Per field, decided by the eval set's comparators server-side. The table
   * must highlight from this and never recompute — client-side equality
   * would call `1240.50` and `1240.5` a disagreement while the field panel
   * above it, using the comparators, calls them agreement.
   *
   * `null` means agreement is undefined (a single config).
   */
  field_agrees: Record<string, boolean | null>;
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

export interface ProviderStatus {
  /** The provider's default Airflow connection exists. */
  configured: boolean;
  /** Names the Airflow connection to create. Never carries a key. */
  reason: string | null;
  /** Airflow conn ids a structure step can pick. */
  connections: string[];
}

/**
 * Which structure providers are configured well enough to offer.
 *
 * Configuration, not validity — a present-but-expired key still fails at
 * call time, and proving otherwise would cost a billable request per load.
 */
export const getStructureProviderStatus = () =>
  apiFetch<{ providers: Record<string, ProviderStatus> }>("/api/providers/structure");

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
  apiFetch<{ run_id: string }>(`/api/pipelines/${encodeURIComponent(pipelineId)}/trigger`, {
    method: "POST",
    body: JSON.stringify({ eval_set_id: evalSetId }),
  });

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

export interface AutomapMatch {
  dest: string;
  source: string | null;
  confidence: number;
  via: "exact" | "fuzzy" | "llm" | null;
  warning: string | null;
}

/** Propose a source→destination column mapping. `use_llm` adds a model pass
 *  over whatever the name heuristics could not place; its failure comes back
 *  as `llm_error`, never as a failed request. */
export const automapFields = (body: {
  source_fields: { name: string; type: string }[];
  dest_fields: { name: string; type: string }[];
  use_llm: boolean;
}) =>
  apiFetch<{ matches: AutomapMatch[]; unmatched_source: string[]; llm_error: string | null }>(
    `/api/schema/automap`,
    { method: "POST", body: JSON.stringify(body) },
  );

/* ── Dashboards (plan 064) ─────────────────────────────────────────────── */

export type ChartKind = "bar" | "line" | "area" | "pie" | "number" | "table";

/**
 * How a tile draws its rows. Presentational only — it never aggregates.
 * Grouping and summing are the `aggregate` step's job, so the Sample rows
 * table and the tile cannot disagree about the same pipeline.
 */
export interface ChartSpec {
  kind: ChartKind;
  /** Category / time axis column. Null for `number` and `table`. */
  x: string | null;
  /** Value columns. Exactly one for `number`; empty only for `table`. */
  y: string[];
  /** Group-by column: one series per distinct value, pivoted client-side. */
  series: string | null;
  stacked: boolean;
}

/** Widths are 12-grid spans, not pixels — a free integer leaves gaps no
 *  layout code can close. */
export type TileWidth = 4 | 6 | 12;
export type TileHeight = "s" | "m" | "l";

export interface DashboardTile {
  id: string;
  title: string;
  pipeline_id: string;
  chart: ChartSpec;
  width: TileWidth;
  height: TileHeight;
  /** Rows this tile pulls through the preview endpoint. Capped at 10k
   *  server-side: preview itself has no upper bound. */
  limit: number;
}

export interface Dashboard {
  id: string;
  name: string;
  description: string | null;
  tiles: DashboardTile[];
}

export const listDashboards = (limit = 50, offset = 0) =>
  apiFetch<Dashboard[]>(`/api/dashboards?limit=${limit}&offset=${offset}`);

export const getDashboard = (id: string) =>
  apiFetch<Dashboard>(`/api/dashboards/${encodeURIComponent(id)}`);

export const createDashboard = (body: Omit<Dashboard, "id"> & { id?: string }) =>
  apiFetch<Dashboard>(`/api/dashboards`, { method: "POST", body: JSON.stringify(body) });

export const updateDashboard = (id: string, body: Dashboard) =>
  apiFetch<Dashboard>(`/api/dashboards/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const deleteDashboard = (id: string) =>
  apiFetch<void>(`/api/dashboards/${encodeURIComponent(id)}`, { method: "DELETE" });
