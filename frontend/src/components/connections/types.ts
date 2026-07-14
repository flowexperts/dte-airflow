import type { ConnectionType } from "@/lib/api";

export const CONNECTION_KINDS: { value: ConnectionType; label: string }[] = [
  { value: "local_fs",  label: "Local filesystem" },
  { value: "s3",        label: "Amazon S3" },
  { value: "gcs",       label: "Google Cloud Storage" },
  { value: "azure",     label: "Azure Blob" },
  { value: "postgres",  label: "PostgreSQL" },
  { value: "mysql",     label: "MySQL" },
  { value: "sqlite",    label: "SQLite" },
  { value: "snowflake", label: "Snowflake" },
  { value: "bigquery",  label: "BigQuery" },
  { value: "mongodb",   label: "MongoDB" },
  { value: "rest_api",  label: "REST API" },
];

export function emptyCredentials(kind: ConnectionType): Record<string, unknown> {
  if (kind === "s3") return { aws_access_key_id: "", aws_secret_access_key: "" };
  if (kind === "gcs") return { hmac_key_id: "", hmac_secret: "" };
  if (kind === "azure") return { azure_storage_account_name: "", azure_storage_account_key: "" };
  if (["postgres", "mysql", "sqlite", "snowflake", "bigquery", "mongodb"].includes(kind))
    return { url: "" };
  if (kind === "rest_api") return { auth: {}, headers: {} };
  return {};
}
