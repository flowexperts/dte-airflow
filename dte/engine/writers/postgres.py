from __future__ import annotations
import ibis
from dte.models.pipeline import PostgresTarget


def write(table: ibis.Table, target: PostgresTarget, con: ibis.BaseBackend | None = None) -> dict:
    import dlt

    arrow_table = table.to_pyarrow()

    @dlt.resource(name=target.table, write_disposition=target.write_disposition)
    def _resource():
        yield arrow_table

    pipeline = dlt.pipeline(
        pipeline_name=f"dte_pg_{target.schema_}_{target.table}",
        destination=dlt.destinations.postgres(credentials=target.credentials),
        dataset_name=target.schema_,
    )
    pipeline.run(_resource())
    return {
        "rows_written": arrow_table.num_rows,
        "location": f"postgres://{target.schema_}.{target.table}",
    }
