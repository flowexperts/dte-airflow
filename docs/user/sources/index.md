# Sources

A source is *where inside a system your data lives*. It picks a [connection](../connections/index.md) and adds the details. The kinds on offer follow the Airflow providers installed; a kind whose provider is missing is shown disabled with the package to install.

## Every source kind

| Kind | Use for | What you fill in |
| ---- | ------- | ---------------- |
| **Filesystem** | Files on the machine dte runs on | Folder, file pattern (e.g. `orders*.json`), optional format |
| **Amazon S3** | Objects in an S3 bucket | Bucket URL (`s3://bucket/path/`), file pattern, optional format |
| **Google Cloud Storage** | Objects in a GCS bucket | Bucket URL (`gs://bucket/path/`), file pattern, optional format |
| **Azure Blob Storage** | Blobs in an Azure container | Bucket URL (`az://container/path/` or `abfs://container/path/`), file pattern, optional format |
| **SFTP** | Files on an SFTP server | Folder URL (`sftp:///path/on/server/` — the host comes from the connection), file pattern, optional format |
| **SQL database** | A table (or a custom query) in Postgres, MySQL, SQL Server, SQLite, Snowflake, or BigQuery | Either **Table** name or a **Query** — not both |
| **MongoDB** | A collection | Database name, collection name |
| **REST API** | Data from a JSON API | Endpoint path, pagination shape, resource details |

## Folders vs files

For file-based sources, the folder field is **a folder, not a single file**. The file pattern picks which files inside it to read. `orders*.json` matches every file starting with `orders` and ending in `.json`; `**/*.json` matches `.json` files in every subfolder.

## File format

dte guesses the format from the file extension. Override with **Format** when it doesn't match:

- `json`, `jsonl`, `ndjson`
- `csv`, `tsv`
- `parquet`
- `excel` (`.xlsx`, first sheet only)

Rules:

- **Wrong family, blocked.** If the pattern is `*.csv` and you pick format `excel`, dte refuses to save.
- **Same family, allowed.** If the pattern is `*.json` and you pick format `jsonl`, dte allows it — that's the "wrong extension, right content" escape hatch.

## Infer schema

Every source form has an **Infer schema** button. Click it. dte reads a small sample and shows the columns it found — including nested ones (like `order.amount`, `user.address.city`).

Do this once per source. The rest of the app — filter fields, rename mappings, select checkboxes — all fill in from what Infer schema found.

## One source, many pipelines

Sources are shared. Editing a source affects every pipeline that reads from it. The source form calls this out so nobody's surprised.

Try to delete a source that's in use — dte tells you which pipelines depend on it before anything happens.
