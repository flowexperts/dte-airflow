export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL || "https://dte.flowexperts.ai").replace(
  /\/$/,
  "",
);
export const APP_URL = process.env.NEXT_PUBLIC_APP_URL || "https://dte.flowexperts.ai";

export const REPO_URL = "https://github.com/flowexperts/dte-airflow";
export const DOCS_URL = `${REPO_URL}/tree/main/docs/user#readme`;
export const INSTALL_URL = `${REPO_URL}/blob/main/docs/user/self-hosting/install.md`;

export const SITE_NAME = "DTE";
export const SITE_TITLE = "DTE — Data Transformation Engine for Apache Airflow";
export const SITE_DESCRIPTION =
  "DTE is an open-source (Apache-2.0) data transformation engine that runs as an Apache Airflow 3 plugin. Map fields once in a visual pipeline builder — filter, rename, retype, lookup, aggregate, join, pivot — and every pipeline becomes an Airflow DAG. Reads files, S3, GCS, Azure Blob, Postgres, MySQL, SQL Server, Snowflake, BigQuery, MongoDB and REST APIs; writes to SQL databases, Parquet on S3 and JSON/CSV/Excel files. Built on DuckDB, ibis and dlt.";
