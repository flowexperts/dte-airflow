from __future__ import annotations

import tempfile

import ibis

from dte.models.pipeline import PostgresTarget


def write(
    table: ibis.Table,
    target: PostgresTarget,
    con: ibis.BaseBackend | None = None,
    credentials: dict | None = None,
) -> dict:
    """`credentials["url"]` is the SQLAlchemy-style Postgres URL."""
    import dlt

    creds = credentials or {}
    if "url" not in creds:
        raise ValueError("postgres destination: connection credentials missing 'url'")

    arrow_table = table.to_pyarrow()

    @dlt.resource(name=target.table, write_disposition=target.write_disposition)
    def _resource():
        yield arrow_table

    # Two things, and the first is useless without the second.
    #
    # `naming_convention="direct"`: the destination table already exists with
    # declared column names, so the identifiers handed to dlt are the ones to
    # write to. dlt's `snake_case` default is for *inferring* a schema from
    # messy source data — it lowercases what it is given, matches no column,
    # and adds one. The load then reports rows written while the column the
    # user mapped to stays null, and nothing raises.
    #
    # `pipelines_dir`: dlt persists a normalised schema per `pipeline_name`
    # and the stored copy wins over the convention, so on any destination
    # written to once already the line above is a no-op. This writer
    # materialises the whole table every run and uses no incremental source,
    # so that state buys nothing — and being container-local it also split
    # between backend and worker. A fresh directory per write removes both.
    with tempfile.TemporaryDirectory(prefix="dte-dlt-") as pipelines_dir:
        pipeline = dlt.pipeline(
            pipeline_name=f"dte_pg_{target.schema_}_{target.table}",
            destination=dlt.destinations.postgres(
                credentials=creds["url"], naming_convention="direct"
            ),
            dataset_name=target.schema_,
            pipelines_dir=pipelines_dir,
        )
        pipeline.run(_resource())
    return {
        "rows_written": arrow_table.num_rows,
        "location": f"postgres://{target.schema_}.{target.table}",
    }
