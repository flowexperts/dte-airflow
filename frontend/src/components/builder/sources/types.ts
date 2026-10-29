import type { Source, ConnectionType } from "@/lib/api";

export type SourceKind =
  | "filesystem"
  | "documents"
  | "s3" | "gcs" | "azure" | "sftp"
  | "sql_database"
  | "mongodb"
  | "rest_api";

export const SOURCE_KINDS: { value: SourceKind; label: string }[] = [
  { value: "filesystem",   label: "Local filesystem" },
  { value: "documents",    label: "Documents (PDF)" },
  { value: "s3",           label: "Amazon S3" },
  { value: "gcs",          label: "Google Cloud Storage" },
  { value: "azure",        label: "Azure Blob" },
  { value: "sftp",         label: "SFTP" },
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
  documents:    ["local_fs", "s3", "gcs", "azure"],
  s3:           ["s3"],
  gcs:          ["gcs"],
  azure:        ["azure"],
  sftp:         ["sftp"],
  sql_database: ["postgres", "mysql", "mssql", "sqlite", "bigquery", "snowflake"],
  mongodb:      ["mongodb"],
  rest_api:     ["rest_api"],
};

/**
 * Empty template for a new source. The `id` is optional and only used as a
 * suggested name when the caller wants to prefill the label ("source_2");
 * on POST the server ignores an empty id and generates a UUID.
 */
export function emptySource(name = ""): Source {
  return {
    id: "",
    name,
    connection_id: "",
    source_type: "filesystem",
    config: { bucket_url: "", file_glob: "*.json" },
    table: name,
  };
}
