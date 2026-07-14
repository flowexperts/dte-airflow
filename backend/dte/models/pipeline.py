from __future__ import annotations
from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field, model_validator


# ─── Connections ─────────────────────────────────────────────────────────

ConnectionType = Literal[
    "local_fs",
    "s3", "gcs", "azure",
    "postgres", "mysql", "sqlite",
    "mongodb", "rest_api",
    "snowflake", "bigquery",
]


# ─── Credential spec sourcing ──────────────────────────────────────────
# We DELEGATE credential validation + field naming to dlt's `@configspec`
# dataclasses. Standardization win: when dlt adds a new integration, we
# add one line to `_DLT_CRED_CLASS` and get validation + field alignment
# for free — a `dlt.destinations.<x>(credentials=creds)` call at the
# writer site just works.
#
# We do NOT inherit from those classes. They're not Pydantic — they're
# `@configspec` dataclasses with internal dunders (`__is_resolved__` etc)
# and dlt-specific machinery. Inheriting drags all of that into our API
# schemas. Instead, at Connection.model_validator time we:
#   1. instantiate the dlt class (raises TypeError on bad fields),
#   2. extract only public fields via `dataclasses.fields()`,
#   3. store those as an opaque dict on the Connection.
# Loaders / writers then reconstruct the dlt object (or hand a URL/dict
# straight to dlt.destinations.<x>) at call time.

from dataclasses import fields as _dc_fields
from dlt.common.configuration.specs import (
    AwsCredentials as _DltAws,
    AzureCredentials as _DltAzure,
    ConnectionStringCredentials as _DltConnStr,
)


class _GcsHmacSpec:
    """Local mini-spec: DuckDB / S3-compatible GCS uses HMAC keys, which
    dlt's `GcpServiceAccountCredentials` (JSON-key auth) can't express."""
    _fields = ("hmac_key_id", "hmac_secret")

    def __init__(self, **kw):
        extra = set(kw) - set(self._fields)
        if extra:
            raise TypeError(f"unexpected keys: {sorted(extra)}")
        for k in self._fields:
            setattr(self, k, kw.get(k))
        if not self.hmac_key_id or not self.hmac_secret:
            raise TypeError("gcs credentials require `hmac_key_id` and `hmac_secret`")


class _RestApiSpec:
    """rest_api auth+headers dict, merged into source config at load time.
    `auth` shape matches dlt's rest_api dict form (e.g. `{"type": "bearer",
    "token": "..."}`) — dlt does its own validation on it."""
    _fields = ("auth", "headers")

    def __init__(self, **kw):
        extra = set(kw) - set(self._fields)
        if extra:
            raise TypeError(f"unexpected keys: {sorted(extra)}")
        self.auth = kw.get("auth") or {}
        self.headers = kw.get("headers") or {}


_DLT_CRED_CLASS: dict[str, type | None] = {
    "local_fs": None,  # no creds
    "s3": _DltAws,
    "gcs": _GcsHmacSpec,
    "azure": _DltAzure,
    "postgres": _DltConnStr,
    "mysql": _DltConnStr,
    "sqlite": _DltConnStr,
    "snowflake": _DltConnStr,
    "bigquery": _DltConnStr,
    "mongodb": _DltConnStr,
    "rest_api": _RestApiSpec,
}


def _instantiate_dlt_cred(cls: type, creds: dict):
    """dlt's `@configspec` classes override __init__ to take one positional
    'native value' (usually a URL). They don't accept kwargs. We probe:
    kwargs first (works for @dataclass-style specs), then fall back to
    passing the dict positionally (works for ConnectionString-style)."""
    try:
        return cls(**creds)
    except TypeError:
        # ConnectionStringCredentials(dict(...)) or ConnectionStringCredentials("url").
        if "url" in creds and len(creds) == 1:
            return cls(creds["url"])
        return cls(creds)


def _public_fields(instance) -> dict:
    """Return field values from a `@configspec` dataclass, skipping
    dlt-internal dunder fields, dlt's built-in defaults, and Nones.

    We drop defaults so a `PUT` with empty credentials leaves the stored
    row minimal (no `aws_sts_token_expiration_hours: 24.0` noise from a
    freshly-constructed AwsCredentials)."""
    # ConnectionString-family: collapse to the URL (loaders and dlt
    # destinations both accept URL strings; single blob is easier to
    # encrypt + audit than the exploded fields).
    if isinstance(instance, _DltConnStr):
        return {"url": instance.to_native_representation()}
    try:
        specced = _dc_fields(instance)
    except TypeError:
        specced = None
    if specced is not None:
        out: dict = {}
        for f in specced:
            if f.name.startswith("__"):
                continue
            v = getattr(instance, f.name)
            if v is None:
                continue
            # Skip dlt's built-in defaults — user didn't set them.
            if f.default is not None and v == f.default:
                continue
            out[f.name] = v
    else:
        out = {name: getattr(instance, name) for name in instance._fields}
        out = {k: v for k, v in out.items() if v is not None}
    return out


class Connection(BaseModel):
    """Reusable credential bundle. `credentials` is validated per
    `connection_type` against dlt's `@configspec` classes — see
    `_DLT_CRED_CLASS`."""
    id: str
    connection_type: ConnectionType
    credentials: dict = {}

    @model_validator(mode="after")
    def _validate_credentials(self):
        cls = _DLT_CRED_CLASS[self.connection_type]
        if cls is None:  # local_fs
            self.credentials = {}
            return self
        try:
            instance = _instantiate_dlt_cred(cls, self.credentials)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"{self.connection_type} credentials invalid: {e}"
            ) from e
        self.credentials = _public_fields(instance)
        return self


# ─── Source configs (per source_type) ─────────────────────────────────────

SourceKind = Literal["filesystem", "s3", "gcs", "azure", "sql_database", "mongodb", "rest_api"]
_FileFormat = Literal["json", "jsonl", "ndjson", "csv", "parquet"]


class _BucketSourceConfig(BaseModel):
    """Shared shape for filesystem + s3 + gcs + azure — everything is a
    directory + glob against an object store or local mount."""
    bucket_url: str
    file_glob: str = "**/*.json"
    format: _FileFormat | None = None
    model_config = {"extra": "forbid"}


class FilesystemSourceConfig(_BucketSourceConfig):
    pass


class S3SourceConfig(_BucketSourceConfig):
    pass


class GcsSourceConfig(_BucketSourceConfig):
    pass


class AzureSourceConfig(_BucketSourceConfig):
    pass


class SqlDatabaseSourceConfig(BaseModel):
    """Points at a table via DuckDB scanner extension. Credentials live on
    the linked Connection (`credentials.url`)."""
    table: str
    schema_: str | None = Field(default=None, alias="schema")
    model_config = {"populate_by_name": True, "extra": "forbid"}


class MongoDBSourceConfig(BaseModel):
    database: str
    collection: str
    filter: dict = {}
    model_config = {"extra": "forbid"}


class RestApiSourceConfig(BaseModel):
    """dlt's rest_api source config surface is large; kept loose so users
    can pass the full dict. Auth + headers should live in the Connection,
    not here."""
    model_config = {"extra": "allow"}


_SOURCE_CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "filesystem": FilesystemSourceConfig,
    "s3": S3SourceConfig,
    "gcs": GcsSourceConfig,
    "azure": AzureSourceConfig,
    "sql_database": SqlDatabaseSourceConfig,
    "mongodb": MongoDBSourceConfig,
    "rest_api": RestApiSourceConfig,
}


class Source(BaseModel):
    id: str
    connection_id: str
    source_type: SourceKind
    config: dict
    table: str

    @model_validator(mode="after")
    def _validate_config(self):
        model = _SOURCE_CONFIG_MODELS[self.source_type]
        # Round-trip through the typed model so extras raise + defaults fill in.
        typed = model(**self.config)
        # `by_alias=True` so `schema_` re-serialises as `schema` on the wire.
        self.config = typed.model_dump(exclude_none=True, by_alias=True)
        return self


# Back-compat alias — deprecated. Delete after plan 015 lands end-to-end.
DltSource = Source


# ─── Steps ────────────────────────────────────────────────────────────────

class FilterStep(BaseModel):
    op: Literal["filter"]
    expr: str


class RenameStep(BaseModel):
    op: Literal["rename"]
    mappings: dict[str, str]


class RetypeStep(BaseModel):
    op: Literal["retype"]
    field: str
    to_type: Literal["string", "int", "float", "boolean", "date", "timestamp"]


class LookupMapStep(BaseModel):
    op: Literal["map"]
    mode: Literal["lookup"]
    field: str
    table: dict[str, str]
    default: str | None = None


class ExpressionMapStep(BaseModel):
    op: Literal["map"]
    mode: Literal["expression", "calculation"]
    output_field: str
    expr: str


class SortStep(BaseModel):
    op: Literal["sort"]
    by: list[str]
    ascending: list[bool] | bool = True


class AggSpec(BaseModel):
    field: str
    func: Literal["sum", "count", "avg", "min", "max", "count_distinct"]
    alias: str


class AggregateStep(BaseModel):
    op: Literal["aggregate"]
    group_by: list[str]
    aggregations: list[AggSpec]


class SelectStep(BaseModel):
    op: Literal["select"]
    fields: list["OutputField"] = []
    drop: list[str] = []

    @model_validator(mode="after")
    def _check_exclusive(self):
        if self.fields and self.drop:
            raise ValueError("SelectStep: `fields` and `drop` are mutually exclusive")
        if not self.fields and not self.drop:
            raise ValueError("SelectStep: one of `fields` or `drop` is required")
        return self


class JoinStep(BaseModel):
    op: Literal["join"]
    left: str
    right: str
    on: str | list[str]
    how: Literal["inner", "left", "right", "outer"] = "inner"
    output_id: str


class PivotStep(BaseModel):
    op: Literal["pivot"]
    index: str | list[str]
    columns: str
    values: str
    agg: Literal["sum", "count", "avg", "min", "max"] = "sum"


class OutputField(BaseModel):
    field: str
    alias: str | None = None


# ─── Output targets (slimmed — creds live on the Connection) ──────────────

class JsonFileTarget(BaseModel):
    type: Literal["json_file"]
    path: str
    fields: list[OutputField] = []


# Back-compat alias for callers still importing the old name.
JsonFileOutput = JsonFileTarget


class CsvFileTarget(BaseModel):
    type: Literal["csv_file"]
    path: str
    fields: list[OutputField] = []


class ParquetS3Target(BaseModel):
    type: Literal["parquet_s3"]
    bucket_url: str
    # `storage_options` removed — creds come from the linked s3 Connection.


class PostgresTarget(BaseModel):
    type: Literal["postgres"]
    schema_: str = Field(alias="schema")
    table: str
    write_disposition: Literal["replace", "append", "merge"] = "replace"
    model_config = {"populate_by_name": True}


class SqlDatabaseTarget(BaseModel):
    type: Literal["sql_database"]
    dialect: Literal["mysql", "snowflake", "bigquery"]
    schema_: str = Field(alias="schema")
    table: str
    write_disposition: Literal["replace", "append", "merge"] = "replace"
    model_config = {"populate_by_name": True}


OutputTarget = Annotated[
    Union[
        JsonFileTarget,
        CsvFileTarget,
        ParquetS3Target,
        PostgresTarget,
        SqlDatabaseTarget,
    ],
    Field(discriminator="type"),
]


class Destination(BaseModel):
    id: str
    connection_id: str
    config: OutputTarget


class Pipeline(BaseModel):
    id: str
    name: str
    sources: list[str]
    steps: list[dict]
    output_id: str


# ─── Connection ↔ Source/Destination compatibility ────────────────────────
# Which connection_types a given source_type / destination type may bind to.
# Enforced in the API save layer (needs the connection lookup).

SOURCE_CONNECTION_COMPAT: dict[str, set[ConnectionType]] = {
    "filesystem": {"local_fs"},
    "s3": {"s3"},
    "gcs": {"gcs"},
    "azure": {"azure"},
    "sql_database": {"postgres", "mysql", "sqlite"},
    "mongodb": {"mongodb"},
    "rest_api": {"rest_api"},
}

DESTINATION_CONNECTION_COMPAT: dict[str, set[ConnectionType]] = {
    "json_file": {"local_fs"},
    "csv_file": {"local_fs"},
    "parquet_s3": {"s3"},
    "postgres": {"postgres"},
    "sql_database": {"mysql", "snowflake", "bigquery"},
}
