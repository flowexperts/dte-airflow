"""One COPY path for every file format and every storage backend.

DuckDB's `COPY … TO '<uri>'` writes local paths and object-store URIs
identically, provided the right extension is loaded and a SECRET exists.
That makes format and location independent: the format decides the
`(FORMAT …)` clause, the URI scheme decides the extension + secret.

Streaming stays inside DuckDB — nothing is buffered through Python, which
is what lets multi-GB results write without blowing up memory.
"""

from __future__ import annotations

import ibis

from dte.sources.duckdb_secrets import backend_for_uri, prepare_object_store

__all__ = ["backend_for_uri", "copy_to"]

_SEQ = iter(range(1, 1 << 30))


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _is_duckdb(backend: ibis.BaseBackend) -> bool:
    return type(backend).__module__.startswith("ibis.backends.duckdb")


def copy_to(
    table: ibis.Table,
    path: str,
    format_clause: str,
    con: ibis.BaseBackend | None = None,
    credentials: dict | None = None,
    extension: str | None = None,
) -> dict:
    """Write `table` to `path` via DuckDB COPY. Returns `{rows_written, location}`.

    `extension` names a DuckDB extension the *format* needs (e.g. `excel`),
    separate from whichever extension the *location* needs.

    `COPY … TO` with these FORMAT clauses is DuckDB grammar, so when the
    result lives in another engine (postgres/mysql/trino/…) it is streamed
    through Arrow into a scratch DuckDB connection first. That keeps file
    and object-store outputs available from every engine rather than only
    from DuckDB-backed pipelines.
    """
    backend = con if con is not None else table._find_backend()

    if _is_duckdb(backend):
        return _copy_from_duckdb(
            backend, table, path, format_clause, credentials, extension, view_of=table
        )

    import duckdb as _duckdb
    import ibis as _ibis

    scratch = _ibis.duckdb.connect()
    # Stream batches rather than materialising the frame in Python; DuckDB
    # spills to disk if the result outgrows memory.
    reader = table.to_pyarrow_batches()
    staged = f"_dte_staged_{next(_SEQ)}"
    scratch.con.register(f"{staged}_reader", reader)
    scratch.con.execute(
        f"CREATE TABLE {_sql_ident(staged)} AS SELECT * FROM {_sql_ident(staged + '_reader')}"
    )
    try:
        return _copy_from_duckdb(
            scratch, None, path, format_clause, credentials, extension,
            view_name=staged,
        )
    finally:
        scratch.con.execute(f"DROP TABLE IF EXISTS {_sql_ident(staged)}")


def _copy_from_duckdb(
    backend,
    table,
    path: str,
    format_clause: str,
    credentials: dict | None,
    extension: str | None,
    view_of=None,
    view_name: str | None = None,
) -> dict:
    raw = backend.con

    # Object-store URIs need their extension + SECRET before COPY runs.
    # Local paths no-op; an unrecognised scheme raises rather than silently
    # creating a file named after the URI.
    prepare_object_store(raw, path, credentials, f"dte_dst_{next(_SEQ)}")

    if extension:
        from dte.sources.duckdb_secrets import _ensure_ext
        _ensure_ext(raw, extension)

    created_view = False
    if view_name is None:
        view_name = f"_dte_out_{next(_SEQ)}"
        backend.create_view(view_name, view_of, overwrite=True)
        created_view = True

    try:
        (rows,) = raw.execute(f"SELECT COUNT(*) FROM {_sql_ident(view_name)}").fetchone()
        raw.execute(
            f"COPY (SELECT * FROM {_sql_ident(view_name)}) TO {_sql_str(path)} ({format_clause})"
        )
    finally:
        if created_view:
            raw.execute(f"DROP VIEW IF EXISTS {_sql_ident(view_name)}")

    return {"rows_written": int(rows), "location": path}
