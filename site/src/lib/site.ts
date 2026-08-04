export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL ?? "https://dte.example.com").replace(
  /\/$/,
  "",
);
export const APP_URL = process.env.NEXT_PUBLIC_APP_URL ?? "https://app.example.com";

export const SITE_NAME = "DTE";
export const SITE_TITLE = "DTE — Data Transformation Engine";
export const SITE_DESCRIPTION =
  "DTE is a batch data transformation engine: connect a source (S3, GCS, Azure, Postgres, MongoDB, REST APIs, filesystem), map fields once with a no-code pipeline builder — filter, rename, retype, lookup, aggregate, join, pivot — and write to any destination (Postgres, SQL databases, Parquet on S3, JSON/CSV/Excel files, REST). Built-in data quality checks and profiling, previewed before every run.";
