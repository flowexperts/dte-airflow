from __future__ import annotations
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

    destination_factory = {
        "mysql": lambda: dlt.destinations.mysql(credentials=url),
        "snowflake": lambda: dlt.destinations.snowflake(credentials=url),
        "bigquery": lambda: dlt.destinations.bigquery(credentials=url),
    }[target.dialect]

    @dlt.resource(name=target.table, write_disposition=target.write_disposition)
    def _resource():
        yield arrow_table

    pipeline = dlt.pipeline(
        pipeline_name=f"dte_{target.dialect}_{target.schema_}_{target.table}",
        destination=destination_factory(),
        dataset_name=target.schema_,
    )
    pipeline.run(_resource())
    return {
        "rows_written": arrow_table.num_rows,
        "location": f"{target.dialect}://{target.schema_}.{target.table}",
    }
