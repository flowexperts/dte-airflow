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
    the target dialect (mysql/mssql/snowflake/bigquery)."""
    import dlt

    creds = credentials or {}
    if "url" not in creds:
        raise ValueError(
            f"{target.dialect} destination: connection credentials missing 'url'"
        )
    url = creds["url"]
    if target.dialect == "mysql" and url.startswith("mysql://"):
        # SQLAlchemy reads the scheme as dialect+driver and defaults bare
        # `mysql://` to mysqldb (mysqlclient), which needs a C toolchain to
        # build. Which driver we use is our business, not the user's — the
        # connection they saved says `mysql://` because that is what the
        # source side takes, and the same URL has to keep working here.
        url = "mysql+pymysql://" + url[len("mysql://"):]

    arrow_table = table.to_pyarrow()

    # See writers/postgres.py for why `direct` and not dlt's snake_case
    # default: the target table already exists, so the identifiers handed
    # to dlt are the ones to write to, and normalising them lands the data
    # in a column nobody asked for with no error raised.
    destination_factory = {
        # dlt ships no first-class mysql destination — mysql reaches it
        # through the `sqlalchemy` one. That is dlt's driver layer, not a
        # target anyone picks: the dialect users choose stays `mysql`, and
        # this dict is the only place that mapping exists. `dlt.destinations
        # .mysql` never existed on any dlt this project pins, so the branch
        # raised AttributeError at write time — after the destination saved
        # and previewed cleanly.
        "mysql": lambda: dlt.destinations.sqlalchemy(
            credentials=url, naming_convention="direct"
        ),
        # dlt reads `driver=` and any ODBC options off the URL's query.
        "mssql": lambda: dlt.destinations.mssql(
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
