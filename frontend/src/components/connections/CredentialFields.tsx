"use client";

import { Field, Input } from "@/components/ui";
import type { ConnectionType } from "@/lib/api";

type CredMap = Record<string, unknown>;

function StringField({
  label,
  hint,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  label: string;
  hint?: string | undefined;
  value: unknown;
  onChange: (v: string) => void;
  placeholder?: string | undefined;
  type?: "text" | "password" | undefined;
}) {
  return (
    <Field label={label} hint={hint}>
      <Input
        type={type}
        value={(value as string) ?? ""}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </Field>
  );
}

/**
 * Per-connection-type credential fields. Field names match dlt's
 * `@configspec` classes so a `dlt.destinations.<x>(credentials=creds)` at
 * the writer site accepts the values without translation.
 */
export function CredentialFields({
  kind,
  credentials,
  onChange,
}: {
  kind: ConnectionType;
  credentials: CredMap;
  onChange: (next: CredMap) => void;
}) {
  const set = (key: string) => (v: string) => onChange({ ...credentials, [key]: v });

  if (kind === "local_fs") {
    return (
      <div className="p-4 text-sm text-subtle">
        Local filesystem has no credentials — this connection is a placeholder
        so every source and destination has a connection to bind to.
      </div>
    );
  }

  if (kind === "s3") {
    return (
      <div className="p-4 grid grid-cols-2 gap-3">
        <StringField label="aws_access_key_id" value={credentials.aws_access_key_id} onChange={set("aws_access_key_id")} />
        <StringField label="aws_secret_access_key" type="password" value={credentials.aws_secret_access_key} onChange={set("aws_secret_access_key")} />
        <StringField label="region_name" hint="e.g. us-east-1" value={credentials.region_name} onChange={set("region_name")} />
        <StringField label="endpoint_url" hint="LocalStack / MinIO override" value={credentials.endpoint_url} onChange={set("endpoint_url")} />
        <StringField label="aws_session_token" hint="optional (STS)" value={credentials.aws_session_token} onChange={set("aws_session_token")} type="password" />
      </div>
    );
  }

  if (kind === "gcs") {
    return (
      <div className="p-4 grid grid-cols-2 gap-3">
        <StringField label="hmac_key_id" value={credentials.hmac_key_id} onChange={set("hmac_key_id")} />
        <StringField label="hmac_secret" type="password" value={credentials.hmac_secret} onChange={set("hmac_secret")} />
      </div>
    );
  }

  if (kind === "azure") {
    return (
      <div className="p-4 grid grid-cols-2 gap-3">
        <StringField label="azure_storage_account_name" value={credentials.azure_storage_account_name} onChange={set("azure_storage_account_name")} />
        <StringField label="azure_storage_account_key" type="password" value={credentials.azure_storage_account_key} onChange={set("azure_storage_account_key")} />
        <StringField label="azure_storage_sas_token" hint="use instead of account_key" value={credentials.azure_storage_sas_token} onChange={set("azure_storage_sas_token")} type="password" />
      </div>
    );
  }

  if (["postgres", "mysql", "sqlite", "snowflake", "bigquery", "mongodb"].includes(kind)) {
    const placeholders: Record<string, string> = {
      postgres: "postgres://user:pass@host:5432/db",
      mysql: "mysql://user:pass@host:3306/db",
      sqlite: "sqlite:///path/to/db.sqlite",
      snowflake: "snowflake://user:pass@account/db?warehouse=wh",
      bigquery: "bigquery://project/dataset",
      mongodb: "mongodb://user:pass@host/db",
    };
    return (
      <div className="p-4">
        <StringField
          label="Connection URL"
          hint="SQLAlchemy-style URL — dlt accepts this directly"
          value={credentials.url}
          onChange={set("url")}
          placeholder={placeholders[kind]}
          type="password"
        />
      </div>
    );
  }

  if (kind === "rest_api") {
    return (
      <div className="p-4 text-sm text-subtle">
        REST API auth: paste your dlt-style `auth` dict below (e.g.
        <code className="mx-1 font-mono text-[11px]">{`{"type":"bearer","token":"..."}`}</code>).
        Headers go under `headers`. The source's `client` config is merged
        with these at load time.
        {/* Kept simple for now — a richer typed editor lands with per-auth
            variants in a follow-up. */}
      </div>
    );
  }

  return null;
}
