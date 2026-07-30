# Destinations

A destination is *where a pipeline's result lands*. Six shapes today.

## Every destination type

| Type | Writes to | What you fill in |
| ---- | --------- | ---------------- |
| **JSON file** | A local `.json`, `.jsonl`, or `.ndjson` file | Path, optional field list |
| **CSV file** | A local `.csv` or `.tsv` | Path, optional field list |
| **Excel file** | A local `.xlsx` (first sheet) | Path, optional field list |
| **Parquet on S3** | A Parquet file in an S3 bucket | Bucket URL |
| **PostgreSQL** | A Postgres table | Schema, table, write mode |
| **SQL database** | A table in MySQL, Snowflake, or BigQuery | Dialect, schema, table, write mode |

## Path has to match the type

Pick **JSON file** and type `orders.csv` in the path? dte stops you at save. This catches "I picked the wrong type" before you run.

Same-family variants are fine: for JSON, all three of `.json`, `.jsonl`, `.ndjson` count.

## Field list (file destinations)

JSON, CSV, and Excel destinations accept an optional **fields** list. Leave it empty and dte writes every column your pipeline produces. Fill it in to write only those columns, in that order, optionally renamed:

| Field | Alias |
| ----- | ----- |
| `id` | *(none)* |
| `customer_name` | `customer` |
| `order.amount` | `amount` |

Nested paths (`order.amount`) work here too — see [Field names](../pipelines/field-refs.md).

For SQL destinations, use a [**Select** step](../steps/index.md) inside the pipeline to control which columns get written.

## Write mode (database destinations)

| Mode | What it does |
| ---- | ------------ |
| **Replace** | Empties the table and inserts. Default. |
| **Append** | Adds rows to what's already there. |
| **Merge** | Updates rows that match the primary key, inserts the rest. Your pipeline output needs to include the key column. |

## What the builder edits inline

The pipeline builder edits **JSON file** destinations right there in the form. For every other type, create it on **Destinations → New** and pick it by name from the builder. When you pick a non-JSON destination inside a pipeline, you'll see a small placeholder card — that's expected; it means the details live on the destination itself.
