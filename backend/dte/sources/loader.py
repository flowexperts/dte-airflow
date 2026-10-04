from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import dlt
import ibis

from dte.models.pipeline import Source

# Object-store plumbing lives in `duckdb_secrets` so the writers can reuse it.
# Re-exported here because `dlt_loader`, `backend_registry` and the unit tests
# import these names from `loader`.
from dte.sources.duckdb_secrets import (  # noqa: F401
    _build_azure_secret_sql,
    _build_gcs_secret_sql,
    _build_s3_secret_sql,
    _ensure_ext,
    _secret_kv,
    _sql_ident,
    _sql_string_literal,
    resolve_secret,
)

if TYPE_CHECKING:
    from dte.engine.backend_registry import BackendRegistry
    from dte.models.pipeline import Connection


_JSONL_EXTS = (".jsonl", ".ndjson")
_JSON_EXTS = (".json",)
_CSV_EXTS = (".csv", ".tsv")
_PARQUET_EXTS = (".parquet", ".pq")
_EXCEL_EXTS = (".xlsx",)


_ALL_KNOWN_EXTS = (
    _JSON_EXTS + _JSONL_EXTS + _CSV_EXTS + _PARQUET_EXTS + _EXCEL_EXTS
)


class UnsupportedFileFormat(ValueError):
    """The glob's extension maps to no DuckDB reader, and no `format` was set.

    Raised instead of guessing. The previous behaviour defaulted to `json`,
    which routed `*.pdf` into `read_json_auto` and surfaced as a JSON parse
    error naming neither the file nor the real problem.
    """


def _detect_format(path: str, explicit: str | None) -> str:
    """`config['format']` wins; otherwise decide by file extension.

    Returns one of: `json`, `jsonl`, `csv`, `parquet`, `excel`.
    Raises `UnsupportedFileFormat` when the extension is unrecognised and no
    explicit format was given — never guesses.
    """
    if explicit:
        fmt = explicit.lower()
        if fmt in ("ndjson",):
            return "jsonl"
        return fmt
    lower = path.lower()
    if lower.endswith(_JSONL_EXTS):
        return "jsonl"
    if lower.endswith(_CSV_EXTS):
        return "csv"
    if lower.endswith(_PARQUET_EXTS):
        return "parquet"
    if lower.endswith(_EXCEL_EXTS):
        return "excel"
    if lower.endswith(_JSON_EXTS):
        return "json"
    raise UnsupportedFileFormat(
        f"cannot detect a file format for {path!r} — extension is not one of "
        f"{', '.join(_ALL_KNOWN_EXTS)}. Set the source's `format` field "
        f"explicitly if the contents differ from the extension."
    )


def _ensure_format_ext(raw_con, fmt: str) -> None:
    """Some DuckDB reader TVFs live in extensions rather than core.
    Idempotently install + load the required extension for `fmt`."""
    if fmt == "excel":
        _ensure_ext(raw_con, "excel")


def _duckdb_reader_call(paths: list[str], fmt: str) -> str:
    """SQL fragment: `read_<fmt>_auto([...])` — a table-valued function call.

    Excel is a `UNION ALL` across `read_xlsx(...)` calls because
    `read_xlsx` doesn't accept a path list. Fine — xlsx sources rarely
    fan out to hundreds of files.
    """
    path_list = "[" + ", ".join(_sql_string_literal(p) for p in paths) + "]"
    if fmt in ("json", "jsonl"):
        arg = "format='newline_delimited'" if fmt == "jsonl" else "format='auto'"
        return f"read_json_auto({path_list}, {arg})"
    if fmt == "csv":
        return f"read_csv_auto({path_list})"
    if fmt == "parquet":
        return f"read_parquet({path_list})"
    if fmt == "excel":
        readers = [
            f"SELECT * FROM read_xlsx({_sql_string_literal(p)})" for p in paths
        ]
        return "(" + " UNION ALL BY NAME ".join(readers) + ")"
    raise ValueError(f"unsupported filesystem format: {fmt!r}")


def _glob_local(bucket_url: str, file_glob: str) -> list[str]:
    """Expand `bucket_url + file_glob` to a sorted list of local paths."""
    import glob as _glob
    from pathlib import Path

    # Strip here as well as at save: sources written before the model-level
    # trim still carry the stray whitespace, and re-saving every one of them
    # is not a reasonable thing to ask.
    bucket_url = bucket_url.strip()
    file_glob = file_glob.strip()

    if bucket_url.startswith("file://"):
        root = bucket_url[len("file://"):]
    else:
        root = bucket_url
    pattern = str(Path(root) / file_glob)
    return sorted(_glob.glob(pattern, recursive=True))


def _load_remote_via_duckdb(
    source: Source,
    registry: "BackendRegistry",
    extension: str,
    secret_sql: str,
) -> ibis.Table:
    """Install the required DuckDB extension, register a scoped SECRET, and
    materialise `bucket_url + file_glob` as a view over `read_*_auto`."""
    con = registry.duckdb()
    raw_con = con.con
    config = source.config
    bucket_url = config["bucket_url"].rstrip("/")
    file_glob = config.get("file_glob", "**/*.json")

    _ensure_ext(raw_con, extension)
    raw_con.execute(secret_sql)

    remote_pattern = f"{bucket_url}/{file_glob}"
    fmt = _detect_format(file_glob, source.format)
    _ensure_format_ext(raw_con, fmt)
    reader_sql = _duckdb_reader_call([remote_pattern], fmt)
    raw_con.execute(
        f"CREATE OR REPLACE VIEW {_sql_ident(source.table)} "
        f"AS SELECT * FROM {reader_sql}"
    )
    return con.table(source.table)


def _load_filesystem(
    source: Source,
    registry: "BackendRegistry",
    connection: "Connection",
    credentials: dict,
) -> ibis.Table:
    """Read local files directly via DuckDB's native readers.

    Nested JSON comes through as STRUCT columns (DuckDB default). The
    compiler's `_resolve_field` traverses dot-form refs (`order.amount`)
    into the struct; legacy `parent__child` refs still work because it
    falls back to `__`-joined lookups when struct traversal misses.
    """
    con = registry.duckdb()
    config = source.config
    bucket_url = config["bucket_url"]
    file_glob = config.get("file_glob", "**/*.json")

    matched = _glob_local(bucket_url, file_glob)
    if not matched:
        raise FileNotFoundError(
            f"No files matched '{file_glob}' in '{bucket_url}'"
        )

    fmt = _detect_format(matched[0], source.format)
    _ensure_format_ext(con.con, fmt)
    reader_sql = _duckdb_reader_call(matched, fmt)
    view_sql = (
        f"CREATE OR REPLACE VIEW {_sql_ident(source.table)} "
        f"AS SELECT * FROM {reader_sql}"
    )
    con.con.execute(view_sql)
    return con.table(source.table)


def _load_s3(
    source: Source,
    registry: "BackendRegistry",
    connection: "Connection",
    credentials: dict,
) -> ibis.Table:
    secret_name = f"dte_src_{source.id}_s3"
    return _load_remote_via_duckdb(
        source, registry, "httpfs", _build_s3_secret_sql(credentials, secret_name)
    )


def _load_gcs(
    source: Source,
    registry: "BackendRegistry",
    connection: "Connection",
    credentials: dict,
) -> ibis.Table:
    secret_name = f"dte_src_{source.id}_gcs"
    return _load_remote_via_duckdb(
        source, registry, "httpfs", _build_gcs_secret_sql(credentials, secret_name)
    )


def _load_azure(
    source: Source,
    registry: "BackendRegistry",
    connection: "Connection",
    credentials: dict,
) -> ibis.Table:
    secret_name = f"dte_src_{source.id}_azure"
    return _load_remote_via_duckdb(
        source, registry, "azure", _build_azure_secret_sql(credentials, secret_name)
    )


def _load_sql_database(
    source: Source,
    registry: "BackendRegistry",
    connection: "Connection",
    credentials: dict,
    table: str | None = None,
) -> ibis.Table:
    """Open a native ibis backend for the linked Connection and return the
    referenced table.  Subsequent compilation pushes filters, projections,
    aggregations etc. down into the source engine (postgres/mysql/sqlite).

    Two sources bound to the same Connection.id share one backend via the
    registry cache, so the compiler treats them as co-located and can join
    them without cross-backend federation.

    Which table to open is a per-pipeline-per-use decision
    (`SourceTableRef.table`) — it is no longer part of the source's own
    `config`, which is why it must be passed in explicitly here rather than
    read off `source.config["table"]`.
    """
    backend = registry.for_connection(connection, credentials)
    config = source.config
    table_name = table
    if not table_name:
        raise ValueError(
            f"source '{source.id}' is sql_database — a table name must be "
            "supplied (SourceTableRef.table / the `table` query param), it "
            "is not stored on the source itself"
        )
    schema = config.get("schema")
    # ibis's SQL backends (postgres/mysql/sqlite) all take `database=` for
    # the schema/database qualifier — `table()` has no `schema=` kwarg.
    if schema:
        return backend.table(table_name, database=schema)
    return backend.table(table_name)


def list_schemas(connection: "Connection", credentials: dict) -> list[str]:
    """List schema/database names visible through a connection's native
    ibis backend. Raises `NotImplementedError` for connection types with no
    native backend (filesystem-family, mongodb, rest_api)."""
    from dte.engine.backend_registry import _open_ibis_backend

    backend = _open_ibis_backend(connection, credentials)
    return list(backend.list_databases())


def list_tables(
    connection: "Connection", credentials: dict, schema: str | None = None
) -> list[str]:
    """List table names visible through a connection's native ibis backend,
    optionally scoped to a schema/database."""
    from dte.engine.backend_registry import _open_ibis_backend

    backend = _open_ibis_backend(connection, credentials)
    if schema:
        return list(backend.list_tables(database=schema))
    return list(backend.list_tables())


def _mongo_client(connection_url: str):
    from pymongo import MongoClient
    return MongoClient(connection_url)


def _load_mongodb(
    source: Source,
    registry: "BackendRegistry",
    connection: "Connection",
    credentials: dict,
) -> ibis.Table:
    con = registry.duckdb()
    raw_con = con.con
    config = source.config
    connection_url = resolve_secret(credentials["url"])
    database = config["database"]
    collection = config["collection"]
    query_filter = config.get("filter", {})

    client = _mongo_client(connection_url)
    coll = client[database][collection]

    @dlt.resource(name=source.table)
    def _mongo_resource():
        for doc in coll.find(query_filter):
            doc.pop("_id", None)
            yield doc

    pipeline = dlt.pipeline(
        pipeline_name=source.id,
        destination=dlt.destinations.duckdb(credentials=raw_con),
        dataset_name="dte_sources",
    )
    pipeline.run(_mongo_resource())
    return con.table(source.table, database=("memory", "dte_sources"))


def _load_rest_api(
    source: Source,
    registry: "BackendRegistry",
    connection: "Connection",
    credentials: dict,
) -> ibis.Table:
    from dlt.sources.rest_api import rest_api_source

    con = registry.duckdb()
    raw_con = con.con
    config = _merge_rest_credentials(source.config, credentials)

    src = rest_api_source(config)
    resources = list(src.resources.values())
    if not resources:
        raise ValueError("rest_api source produced no resources")
    resource = resources[0].with_name(source.table)

    pipeline = dlt.pipeline(
        pipeline_name=source.id,
        destination=dlt.destinations.duckdb(credentials=raw_con),
        dataset_name="dte_sources",
    )
    pipeline.run(resource)
    return con.table(source.table, database=("memory", "dte_sources"))


def _merge_rest_credentials(config: dict, credentials: dict) -> dict:
    """Return a fresh rest_api config with `client.auth` and `client.headers`
    merged from the linked Connection's credentials. Values are still
    passed through `resolve_secret()` for `{env: X}` back-compat."""
    import copy
    resolved = copy.deepcopy(config)
    client = resolved.setdefault("client", {})
    for key in ("auth", "headers"):
        if key in credentials and isinstance(credentials[key], dict):
            merged = dict(client.get(key) or {})
            for k, v in credentials[key].items():
                merged[k] = resolve_secret(v)
            client[key] = merged
    return resolved


LoaderFn = Callable[[Source, "BackendRegistry", "Connection", dict], ibis.Table]

# Extension → media type for the document listing. Deliberately small: it
# covers what the extract providers can actually consume plus the modalities
# plan 050 defers (audio, image, video), so a listing is honest about what it
# found even before a provider exists for it.
_MEDIA_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".html": "text/html",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tiff": "image/tiff",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
}


def _load_documents(
    source: Source,
    registry: "BackendRegistry",
    connection: "Connection",
    credentials: dict,
) -> ibis.Table:
    """List documents — one row per file. **Parses nothing.**

    Extraction happens only when an `extract` step runs. Keeping this lazy is
    what makes `POST /api/schema/infer` instant and free, which matters
    because the builder fires it automatically on every edit; if listing
    parsed PDFs, every keystroke in the UI would cost money.

    Columns: path, filename, ext, size_bytes, modified_at, media_type.
    From here it is ordinary tabular data — every existing step works on it.
    """
    con = registry.duckdb()
    config = source.config
    bucket_url = config["bucket_url"]
    file_glob = config.get("file_glob", "**/*.pdf")

    matched = _glob_local(bucket_url, file_glob)
    if not matched:
        raise FileNotFoundError(
            f"No files matched '{file_glob}' in '{bucket_url}'"
        )

    from datetime import datetime, timezone
    from pathlib import Path

    rows = []
    for path in matched:
        p = Path(path)
        stat = p.stat()
        ext = p.suffix.lower()
        rows.append(
            {
                "path": str(p),
                "filename": p.name,
                "ext": ext,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                "media_type": _MEDIA_TYPES.get(ext, "application/octet-stream"),
            }
        )

    # Registered via a temp table rather than a reader TVF: the listing is
    # already materialised in Python (stat() has no SQL equivalent), and this
    # keeps the result a plain ibis table like every other loader returns.
    import pyarrow as pa

    con.con.register(f"__doc_listing_{source.table}", pa.Table.from_pylist(rows))
    con.con.execute(
        f"CREATE OR REPLACE VIEW {_sql_ident(source.table)} AS "
        f"SELECT * FROM __doc_listing_{source.table}"
    )
    return con.table(source.table)


LOADERS: dict[str, LoaderFn] = {
    "filesystem": _load_filesystem,
    "documents": _load_documents,
    "s3": _load_s3,
    "gcs": _load_gcs,
    "azure": _load_azure,
    "sql_database": _load_sql_database,
    "mongodb": _load_mongodb,
    "rest_api": _load_rest_api,
}


def load_source(
    source: Source,
    registry_or_con: "BackendRegistry | ibis.BaseBackend",
    connection_or_credentials: "Connection | dict | None" = None,
    credentials: dict | None = None,
    table: str | None = None,
) -> ibis.Table:
    """Load a source into an ibis.Table via the appropriate backend.

    - Filesystem-family and dlt-hop loaders use ``registry.duckdb()``.
    - ``sql_database`` uses ``registry.for_connection(connection, creds)``
      so subsequent compilation pushes down into the source engine.

    Signature: ``load_source(source, registry, connection, credentials)``.

    ``table`` — the pipeline-level `SourceTableRef.table` (or an explicit
    override, e.g. for schema introspection). Only meaningful for
    ``sql_database`` sources, which no longer carry a table in their own
    `config` — which table is read is a per-pipeline-per-use decision, not
    part of the source. Every other loader ignores it — the source's own
    config already names what it loads (bucket_url/glob, collection, etc).

    A legacy 3-arg call — ``load_source(source, con, credentials)`` where
    ``con`` is an ``ibis.BaseBackend`` — is still accepted for one release
    to give call sites time to migrate.  The connection is fabricated from
    the source's ``source_type`` and (for ``sql_database``) the URL scheme.
    """
    if isinstance(registry_or_con, ibis.BaseBackend):
        # Legacy: (source, con, credentials).
        from dte.engine.backend_registry import BackendRegistry
        creds: dict = connection_or_credentials or {}  # type: ignore[assignment]
        registry = BackendRegistry(duckdb_con=registry_or_con)
        connection = _fabricate_legacy_connection(source, creds)
    else:
        registry = registry_or_con
        connection = connection_or_credentials  # type: ignore[assignment]
        creds = credentials or {}

    loader = LOADERS.get(source.source_type)
    if loader is None:
        raise NotImplementedError(
            f"source_type '{source.source_type}' is not supported"
        )
    if source.source_type == "sql_database":
        return loader(source, registry, connection, creds, table=table)
    return loader(source, registry, connection, creds)


def _fabricate_legacy_connection(source: Source, credentials: dict) -> "Connection":
    """Build a minimal in-memory Connection from a legacy 3-arg call.

    Only used by pre-registry callers (older tests).  Real API traffic
    passes a real Connection through the routes.
    """
    from dte.models.pipeline import Connection

    ctype: str
    if source.source_type == "sql_database":
        # Resolve env-indirection {"env": "X"} so URL-scheme sniffing works.
        raw_url = credentials.get("url")
        try:
            resolved_url = resolve_secret(raw_url) if raw_url else ""
        except KeyError:
            resolved_url = ""
        url = str(resolved_url)
        if url.startswith("sqlite:"):
            ctype = "sqlite"
        elif url.startswith(("postgres:", "postgresql:")):
            ctype = "postgres"
        elif url.startswith("mysql:"):
            ctype = "mysql"
        elif url.startswith("mssql:"):
            ctype = "mssql"
        elif url.startswith("snowflake:"):
            ctype = "snowflake"
        elif url.startswith("bigquery:"):
            ctype = "bigquery"
        else:
            scheme = url.split("://", 1)[0] if "://" in url else url
            raise NotImplementedError(
                f"sql_database: unsupported credentials scheme '{scheme}://'. "
                "Supported: sqlite, postgresql, mysql, mssql, snowflake, bigquery."
            )
    else:
        # filesystem-family, mongodb, rest_api — all route through DuckDB;
        # connection type is nominal.
        ctype = source.source_type if source.source_type in (
            "s3", "gcs", "azure", "mongodb", "rest_api",
        ) else "local_fs"
    return Connection(
        id=f"legacy_{source.id}",
        connection_type=ctype,  # type: ignore[arg-type]
        credentials=credentials,
    )
