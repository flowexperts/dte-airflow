# Connections

A connection is dte's login to one system — a database, a cloud bucket, an API. It holds credentials only. It doesn't know which table or which folder.

## Why the split

Sources and destinations point at a connection by name. This means:

- **Rotate credentials once.** Update the connection, every pipeline that uses it picks up the new value on the next run.
- **Share safely.** Two pipelines reading different tables in the same database share one connection.
- **See what's at risk.** Try to delete a connection that's in use — dte tells you exactly which sources and destinations depend on it before anything changes.

## Every connector

| Type | Use it for | What you fill in |
| ---- | ---------- | ---------------- |
| **Local files** | Files on the machine dte runs on | Nothing — no credentials |
| **Amazon S3** | Reading & writing S3 buckets | Access key, secret, region, (optional) endpoint URL for MinIO or S3-compatible stores |
| **Google Cloud Storage** | Reading GCS buckets | HMAC key ID and HMAC secret (create in GCP → Storage → Settings → Interoperability). Service-account JSON keys are **not** accepted. |
| **Azure Blob Storage** | Reading Azure containers | Connection string, *or* account name + account key |
| **PostgreSQL** | Reading tables, writing tables | Connection URL, e.g. `postgresql://user:pass@host:5432/db` |
| **MySQL** | Reading tables, writing tables | Connection URL |
| **SQLite** | Reading local `.db` files | Connection URL, e.g. `sqlite:////data/warehouse.db` |
| **Snowflake** | Reading tables, writing tables | Connection URL |
| **BigQuery** | Reading tables, writing tables | Connection URL |
| **MongoDB** | Reading collections | Connection URL, e.g. `mongodb://user:pass@host:27017` |
| **REST API** | Pulling data from a JSON API | Auth (bearer token, basic, etc.) and optional headers |

## Env variable trick for secrets

Any password or secret field can be filled with a **reference** instead of the real value:

```
{env: "AWS_SECRET_ACCESS_KEY"}
```

dte looks up the real value from the app's environment at run time. Handy when you'd rather keep the real secret out of the database entirely. If you're on the hosted app, ask your admin which env variables are available.

## Test before you use

Every connection has a **Test** button. Click it. dte tries to reach the system and reports back:

- ✓ **OK** — you're good. Wire it into a source or destination.
- ✗ **Failed** — the reason shows up right below the button. Common ones:

| What you see | What's usually wrong |
| ------------ | -------------------- |
| `403` on S3/GCS | Wrong keys, wrong region, or the bucket doesn't allow list |
| `NoSuchBucket` | Wrong region or endpoint URL |
| `connection refused` on a database | Wrong host or port, or the app can't reach it |
| `password authentication failed` | Wrong credentials in the URL |

Fix and test again. A failure caught here is one you won't chase inside a pipeline run.

## Which connector goes with which source / destination

Not every combination is valid. dte will stop you at save if you pick a mismatched pair.

- **Local files** → filesystem sources; JSON, CSV, Excel file destinations
- **Amazon S3** → S3 sources; Parquet-on-S3 destinations
- **Google Cloud Storage** → GCS sources
- **Azure Blob Storage** → Azure sources
- **PostgreSQL** → SQL database sources; PostgreSQL destinations
- **MySQL / Snowflake / BigQuery** → SQL database sources; SQL database destinations
- **SQLite** → SQL database sources (read only)
- **MongoDB** → MongoDB sources
- **REST API** → REST API sources
