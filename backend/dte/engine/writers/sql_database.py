from __future__ import annotations

import tempfile

import ibis

from dte.models.pipeline import SqlDatabaseTarget


def write(
    table: ibis.Table,
    target: SqlDatabaseTarget,
    con: ibis.BaseBackend | None = None,
    credentials: dict | None = None,
) -> dict:
    """`credentials["url"]` is the SQLAlchemy-style connection string for
    the target dialect (mysql/snowflake/bigquery)."""
    import dlt

    creds = credentials or {}
    if "url" not in creds:
        raise ValueError(
            f"{target.dialect} destination: connection credentials missing 'url'"
        )
    url = creds["url"]

    arrow_table = table.to_pyarrow()

    # See writers/postgres.py for why `direct` and not dlt's snake_case
    # default: the target table already exists, so the identifiers handed
    # to dlt are the ones to write to, and normalising them lands the data
    # in a column nobody asked for with no error raised.
    destination_factory = {
        "mysql": lambda: dlt.destinations.mysql(
            credentials=url, naming_convention="direct"
        ),
        "snowflake": lambda: dlt.destinations.snowflake(
            credentials=url, naming_convention="direct"
        ),
        "bigquery": lambda: dlt.destinations.bigquery(
            credentials=url, naming_convention="direct"
        ),
    }[target.dialect]

    @dlt.resource(name=target.table, write_disposition=target.write_disposition)
    def _resource():
        yield arrow_table

    # `naming_convention` and the throwaway `pipelines_dir` are a pair — see
    # writers/postgres.py for why neither works without the other.
    with tempfile.TemporaryDirectory(prefix="dte-dlt-") as pipelines_dir:
        pipeline = dlt.pipeline(
            pipeline_name=f"dte_{target.dialect}_{target.schema_}_{target.table}",
            destination=destination_factory(),
            dataset_name=target.schema_,
            pipelines_dir=pipelines_dir,
        )
        pipeline.run(_resource())
    return {
        "rows_written": arrow_table.num_rows,
        "location": f"{target.dialect}://{target.schema_}.{target.table}",
    }
