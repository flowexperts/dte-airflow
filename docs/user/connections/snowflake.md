# Snowflake

Read Snowflake tables, transform them, and write results back to Snowflake or to files. Filters, joins and aggregates on tables from the same connection run inside Snowflake as one query; only the result reaches the worker.

## 1. Create a user for dte

Use a service user with key-pair auth. Snowflake is retiring password-only sign-in, and accounts created with SSO or OAuth have no password to give dte.

Generate a key on your machine:

```bash
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8 -nocrypt
openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub
```

Then run this in a Snowsight worksheet as `ACCOUNTADMIN`. Paste the body of `rsa_key.pub` without the `-----BEGIN/END-----` lines:

```sql
CREATE WAREHOUSE IF NOT EXISTS DTE_WH
  WAREHOUSE_SIZE = XSMALL AUTO_SUSPEND = 60 AUTO_RESUME = TRUE INITIALLY_SUSPENDED = TRUE;

CREATE ROLE IF NOT EXISTS DTE_ROLE;
GRANT USAGE ON WAREHOUSE DTE_WH TO ROLE DTE_ROLE;

-- read: grant what your sources need, e.g. the sample data
GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE_SAMPLE_DATA TO ROLE DTE_ROLE;

-- write: a database the role owns
CREATE DATABASE IF NOT EXISTS DTE_OUT;
GRANT OWNERSHIP ON DATABASE DTE_OUT TO ROLE DTE_ROLE;
GRANT OWNERSHIP ON SCHEMA DTE_OUT.PUBLIC TO ROLE DTE_ROLE;

CREATE USER IF NOT EXISTS DTE_SVC
  TYPE = SERVICE DEFAULT_ROLE = DTE_ROLE DEFAULT_WAREHOUSE = DTE_WH
  RSA_PUBLIC_KEY = '<public key body>';
GRANT ROLE DTE_ROLE TO USER DTE_SVC;
```

Passwords and the provider's OAuth options work too. dte builds the client from the Airflow hook, so whatever the [Snowflake provider](https://airflow.apache.org/docs/apache-airflow-providers-snowflake/stable/connections/snowflake.html) accepts, dte accepts.

## 2. Add the Airflow connection

One connection per database. A source reads the database its connection names, and a destination writes to it, so reading from one database and writing to another takes two connections.

**Admin → Connections → +**, type **Snowflake**:

| Field | Value |
| ----- | ----- |
| Login | `DTE_SVC` |
| Schema | default schema, e.g. `TPCH_SF1` |
| Account | `<locator>.<region>.<cloud>`, e.g. `hu54554.ap-southeast-7.aws` (from your Snowsight URL) |
| Database | e.g. `SNOWFLAKE_SAMPLE_DATA` |
| Warehouse / Role | `DTE_WH` / `DTE_ROLE` |
| Private key (text) | the contents of `rsa_key.p8` |

Or from the CLI, with the key base64-encoded:

```bash
airflow connections add snowflake_read --conn-json "$(cat <<EOF
{"conn_type": "snowflake", "login": "DTE_SVC", "schema": "TPCH_SF1",
 "extra": {"account": "hu54554.ap-southeast-7.aws", "database": "SNOWFLAKE_SAMPLE_DATA",
           "warehouse": "DTE_WH", "role": "DTE_ROLE",
           "private_key_content": "$(base64 < rsa_key.p8 | tr -d '\n')",
           "dte_statement_timeout_seconds": 300}}
EOF
)"
```

The account goes in the extras, not the host. A URI like `snowflake://user@account/db` fails with `account parameter must be specified`.

## 3. Source, destination, pipeline

- **Source:** type **SQL database**, the Snowflake connection, schema `TPCH_SF1`. Every table in the schema becomes available to pipelines.
- **Destination:** type **SQL database**, dialect `snowflake`, schema and table (`PUBLIC`, `REVENUE_BY_NATION`), and a write mode. The table is created on the first run. dlt also adds `_dlt_loads`, `_dlt_pipeline_state` and `_dlt_version` tables to the schema.
- **Pipeline:** pick tables from the source as usual. Snowflake column names are upper case (`O_TOTALPRICE`), so refer to them that way in steps and filters.

## Cost

Snowflake bills **warehouse time**, not bytes. A warehouse that's running costs credits whether a query scans 1 KB or 1 TB. X-Small is 1 credit an hour, and each size up doubles it. Every resume bills at least 60 seconds. A credit costs about $2–4, depending on edition and region.

What dte does about it:

- **Preview runs when you click it.** A pipeline with a Snowflake source doesn't preview as you edit. **Preview** reads a ~1% block sample of each table (`TABLESAMPLE SYSTEM (1)`), caches it, and previews against that. **Preview on live data** queries the real tables.
- **Only large runs ask.** Before a run or live preview, dte checks the query plan (`EXPLAIN`, free) for how much it reads. Under 10 GiB it just runs. Over that, the Run dialog says *This is a large query: it reads about 20 GiB. Snowflake bills for every minute the DTE_WH warehouse runs, and this connection stops a query after 5 minutes.* dte names the warehouse and the time limit rather than a price, because those are what Snowflake bills for. Change the threshold with `dte_confirm_above_bytes` in the connection extras (`0` asks every time).
- **Statement timeout.** Set `dte_statement_timeout_seconds` in the connection extras. dte sets `STATEMENT_TIMEOUT_IN_SECONDS` on every session it opens (preview, run, schema lookup), so Snowflake kills a runaway query.
- **`--sample N` / `DTE_RUN_MAX_ROWS` cap output rows, not the scan.** A pipeline that aggregates still reads the whole input.

What to do on your side:

- Give dte its own X-Small warehouse with `AUTO_SUSPEND = 60`, as above. Scheduled pipelines then show up as their own line in `WAREHOUSE_METERING_HISTORY`.
- Put a [resource monitor](https://docs.snowflake.com/en/user-guide/resource-monitors) on that warehouse to suspend it at a credit quota.
- Filter early. Filters and joins push down, so a filter on a clustered date column cuts what Snowflake scans.

## Limits

- **No cross-database joins in one pipeline.** A Snowflake table can't be joined with a file or a table from another connection unless the pipeline runs on Trino. Write one side to the other first.
- **Merge needs a key it doesn't have yet.** The write mode `merge` has no primary key to match on and behaves like `append`. Use `replace` for full refreshes.
- **Writes go through the worker.** The result is pulled into worker memory, then loaded with dlt. Size the worker for the output.
