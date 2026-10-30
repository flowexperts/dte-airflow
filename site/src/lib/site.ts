import type { Metadata } from "next";


export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL || "https://dte.flowexperts.ai").replace(
  /\/$/,
  "",
);
export const APP_URL = process.env.NEXT_PUBLIC_APP_URL || "https://dte.flowexperts.ai";

export const REPO_URL = "https://github.com/flowexperts/dte-airflow";
// Docs are a VitePress build served at /docs/ (docs-vp/).
export const DOCS_URL = "/docs/";
export const INSTALL_URL = `${DOCS_URL}self-hosting/install-plugin`;

export const SITE_NAME = "DTE";
export const SITE_TITLE = "DTE — Data Transformation Engine for Apache Airflow";
export const SITE_DESCRIPTION =
  "DTE is an open-source (Apache-2.0) data transformation engine that installs with pip into Apache Airflow 3.3+ as a plugin. Map fields once in a visual pipeline builder — filter, rename, retype, lookup, aggregate, join, pivot — and every pipeline becomes an Airflow DAG. Reads files, S3, GCS, Azure Blob, SFTP, Postgres, MySQL, SQL Server, Snowflake, BigQuery, MongoDB and REST APIs; writes to SQL databases and Parquet/JSON/CSV/Excel files locally or in object storage. Uses your Airflow connections, through whatever providers are installed. Built on DuckDB, ibis and dlt.";

/** Per-page metadata. Next replaces (not merges) a parent's openGraph/twitter,
 *  so every page sets its own or it previews as the homepage. */
export function pageMeta(title: string, description: string, path: string): Metadata {
  return {
    title,
    description,
    alternates: { canonical: path },
    openGraph: {
      type: "website",
      siteName: SITE_NAME,
      locale: "en_US",
      url: `${SITE_URL}${path}`,
      title: `${title} — ${SITE_NAME}`,
      description,
    },
    twitter: { card: "summary_large_image", title: `${title} — ${SITE_NAME}`, description },
  };
}
