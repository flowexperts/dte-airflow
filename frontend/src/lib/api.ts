import type { components, paths } from "./api-types";

export type JsonFileOutput = components["schemas"]["JsonFileTarget"];
export type OutputField = components["schemas"]["OutputField"];

/**
 * Pipeline model — hand-typed because api-types.ts is stale until
 * `pnpm gen:types` regens against the new backend.
 */
export interface Pipeline {
  id: string;
  name: string;
  sources: string[];
  steps: Array<Record<string, unknown>>;
  output_id: string;
}

/** Source model — same shape as the former DltSource; renamed backend-side. */
export interface Source {
  id: string;
  source_type: string;
  config: Record<string, unknown>;
  table: string;
}

/** Back-compat re-export for callers still importing the old name. */
export type DltSource = Source;

/**
 * OutputTarget discriminated union — mirrors the backend's Pydantic union.
 * We hand-type it because Destination.config isn't yet in api-types until
 * the openapi regen runs.
 */
export type OutputTarget =
  | JsonFileOutput
  | { type: "csv_file"; path: string; fields?: OutputField[] }
  | { type: "parquet_s3"; bucket_url: string; storage_options?: Record<string, unknown> }
  | { type: "postgres"; credentials: string; schema: string; table: string; write_disposition?: "replace" | "append" | "merge" }
  | { type: "sql_database"; dialect: "mysql" | "snowflake" | "bigquery"; credentials: string; schema: string; table: string; write_disposition?: "replace" | "append" | "merge" };

export interface Destination {
  id: string;
  config: OutputTarget;
}

/** Discriminated narrowing helper — the UI only edits json_file targets today. */
export function isJsonFileOutput(o: OutputTarget): o is JsonFileOutput {
  return o.type === "json_file";
}

// Run is untyped in OpenAPI (routes return `dict`), so we model it here.
export type RunStatus = "pending" | "running" | "completed" | "failed";
export interface Run {
  id: string;
  pipeline_id: string;
  status: RunStatus;
  error: string | null;
  rows_written: number | null;
  location: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface SchemaField {
  name: string;
  type: string;
  children?: SchemaField[] | null;
}

export interface PreviewResponse {
  rows: Array<Record<string, unknown>>;
  count: number;
}

const BASE =
  typeof window === "undefined"
    ? process.env.INTERNAL_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001"
    : process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
    public url: string,
  ) {
    super(`${status} ${detail} (${url})`);
    this.name = "ApiError";
  }
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const url = path.startsWith("http") ? path : `${BASE}${path}`;
  const res = await fetch(url, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
    } catch {
      // non-json error
    }
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail), url);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
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

export const triggerPipeline = (id: string) =>
  apiFetch<{ run_id: string }>(
    `/api/pipelines/${encodeURIComponent(id)}/trigger`,
    { method: "POST" },
  );

export const previewPipeline = (id: string, limit = 100) =>
  apiFetch<PreviewResponse>(
    `/api/pipelines/${encodeURIComponent(id)}/preview?limit=${limit}`,
  );

export const listPipelineRuns = (id: string, limit = 50) =>
  apiFetch<Run[]>(
    `/api/pipelines/${encodeURIComponent(id)}/runs?limit=${limit}`,
  );

// ---------- Sources ----------

export const listSources = () => apiFetch<Source[]>(`/api/sources`);
export const getSource = (id: string) => apiFetch<Source>(`/api/sources/${encodeURIComponent(id)}`);
export const createSource = (source: Source) =>
  apiFetch<Source>(`/api/sources`, { method: "POST", body: JSON.stringify(source) });
export const updateSource = (id: string, source: Source) =>
  apiFetch<Source>(`/api/sources/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(source) });
export const deleteSource = (id: string) =>
  apiFetch<void>(`/api/sources/${encodeURIComponent(id)}`, { method: "DELETE" });
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

// ---------- Runs ----------

export const getRun = (id: string) =>
  apiFetch<Run>(`/api/runs/${encodeURIComponent(id)}`);

export const getRunOutput = (id: string, limit = 5) =>
  apiFetch<PreviewResponse>(
    `/api/runs/${encodeURIComponent(id)}/output?limit=${limit}`,
  );

export const inferSchema = (source: Source) =>
  apiFetch<{ fields: SchemaField[] }>(`/api/schema/infer`, {
    method: "POST",
    body: JSON.stringify(source),
  });

export const isTerminal = (status: RunStatus | undefined): boolean =>
  status === "completed" || status === "failed";

// re-export the OpenAPI namespaces for consumers wanting the raw types
export type { components, paths };
