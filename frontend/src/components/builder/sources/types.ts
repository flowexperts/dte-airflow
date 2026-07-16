import type { Source, ConnectionType } from "@/lib/api";

export type SourceKind =
  | "filesystem"
  | "s3" | "gcs" | "azure"
  | "sql_database"
  | "mongodb"
  | "rest_api";

export const SOURCE_KINDS: { value: SourceKind; label: string }[] = [
  { value: "filesystem",   label: "Local filesystem" },
  { value: "s3",           label: "Amazon S3" },
  { value: "gcs",          label: "Google Cloud Storage" },
  { value: "azure",        label: "Azure Blob" },
  { value: "sql_database", label: "SQL database" },
  { value: "mongodb",      label: "MongoDB" },
  { value: "rest_api",     label: "REST API" },
];

/**
 * Which Connection types are compatible with a given source_type.
 * Mirrors backend's `SOURCE_CONNECTION_COMPAT` — kept in sync manually.
 */
export const SOURCE_CONNECTION_COMPAT: Record<SourceKind, ConnectionType[]> = {
  filesystem:   ["local_fs"],
  s3:           ["s3"],
  gcs:          ["gcs"],
  azure:        ["azure"],
  sql_database: ["postgres", "mysql", "sqlite"],
  mongodb:      ["mongodb"],
  rest_api:     ["rest_api"],
};

export function emptySource(id = ""): Source {
  return {
    id,
    connection_id: "",
    source_type: "filesystem",
    config: { bucket_url: "", file_glob: "*.json" },
    table: id,
  };
}
