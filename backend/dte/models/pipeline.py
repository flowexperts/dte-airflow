from __future__ import annotations
from datetime import datetime
from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import Column, LargeBinary, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field as SMField, SQLModel


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


# ─── Connection (SQLModel — single class serves API validation + persistence) ──
#
# `ConnectionBase` holds domain fields. `Connection` (table=True) adds the
# persistence columns including `credentials_encrypted` (BYTEA). `credentials`
# lives only on `ConnectionBase`/`ConnectionCreate` — SQLModel cannot map a
# plain `dict` column without an explicit `sa_column`, so we keep it off the
# table class and let the store layer decrypt into a dynamic attribute.
#
# `ConnectionCreate` is the FastAPI input shape and carries the credential
# validator — the `table=True` class must not carry it because ORM hydration
# bypasses Pydantic's required-field checks.

class ConnectionBase(SQLModel):
    """Base domain fields — no persistence identity, no encryption.

    `connection_type` is typed as `str` here so SQLModel can map it to a TEXT
    column without tripping on Literal[...] — which SQLModel 0.0.x cannot
    resolve to a SA type. `ConnectionCreate` overrides it with the Literal for
    strict validation at the API edge.
    """
    connection_type: str = SMField(sa_column=Column(Text, nullable=False))


class Connection(ConnectionBase, table=True):
    """ORM-mapped row. `credentials` is NOT a mapped column — it is set as a
    plain Python attribute by the store after decryption. `model_dump()` will
    NOT include it; routes build the response dict manually."""
    __tablename__ = "connections"

    id: str = SMField(primary_key=True)
    credentials_encrypted: bytes = SMField(
        sa_column=Column(LargeBinary, nullable=False)
    )
    created_at: datetime | None = SMField(
        default=None, sa_column=Column(server_default=func.now())
    )
    updated_at: datetime | None = SMField(
        default=None,
        sa_column=Column(server_default=func.now(), onupdate=func.now()),
    )

    def credentials_dict(self) -> dict:
        """Return the `credentials` attribute set by the store, or {} if
        the store hasn't populated it (e.g. list path masks them)."""
        return getattr(self, "credentials", {})

    def to_api_dict(self) -> dict:
        """Serialise for API responses: id + connection_type + credentials."""
        return {
            "id": self.id,
            "connection_type": self.connection_type,
            "credentials": self.credentials_dict(),
        }


class ConnectionCreate(ConnectionBase):
    """Strict API input — non-table so required-field checks fire.

    Overrides `connection_type` with the `ConnectionType` Literal so
    Pydantic rejects unknown types at the API edge.
    """
    id: str
    connection_type: ConnectionType  # type: ignore[override]
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
_FileFormat = Literal["json", "jsonl", "ndjson", "csv", "parquet", "excel"]


class _BucketSourceConfig(BaseModel):
    """Shared shape for filesystem + s3 + gcs + azure — everything is a
    directory + glob against an object store or local mount.

    `format` lives on `Source` (top-level column since migration 009),
    not here.
    """
    bucket_url: str
    file_glob: str = "**/*.json"
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


_FILESYSTEM_KINDS = {"filesystem", "s3", "gcs", "azure"}

# Family the extension belongs to. Format ↔ extension pairs are OK as
# long as they land in the same family. This tolerates the real-world
# case of `.json` files that are actually NDJSON (both "json family"),
# while still catching genuinely wrong pairings like `format=excel` +
# `*.csv`.
_EXT_FAMILY: dict[str, str] = {
    ".json":    "json",
    ".jsonl":   "json",
    ".ndjson":  "json",
    ".csv":     "csv",
    ".tsv":     "csv",
    ".parquet": "parquet",
    ".pq":      "parquet",
    ".xlsx":    "excel",
}

_FORMAT_FAMILY: dict[str, str] = {
    "json":    "json",
    "jsonl":   "json",
    "ndjson":  "json",
    "csv":     "csv",
    "parquet": "parquet",
    "excel":   "excel",
}

# Family a file-shaped destination writes into. Used to enforce that
# `path` (or `bucket_url` for parquet_s3) matches the target's `type`:
# `json_file` at `orders.csv` is silent nonsense, so we reject at save.
_DEST_FAMILY: dict[str, str] = {
    "json_file":  "json",
    "csv_file":   "csv",
    "excel_file": "excel",
    "parquet_s3": "parquet",
}

_FAMILY_CANONICAL_EXT: dict[str, str] = {
    "json":    ".json",
    "csv":     ".csv",
    "excel":   ".xlsx",
    "parquet": ".parquet",
}


def _check_dest_path_extension(
    dest_type: str, path: str, field_name: str = "path"
) -> None:
    """Refuse when the file's extension doesn't match the destination
    type's family. Missing extension is rejected too — silent typing
    of a naked filename would produce a file with no discoverable
    format hint on disk. Case-insensitive; `.jsonl`/`.ndjson` are
    accepted for `json_file` (same family)."""
    family = _DEST_FAMILY[dest_type]
    ext = _glob_extension(path)
    canonical = _FAMILY_CANONICAL_EXT[family]
    if not ext:
        raise ValueError(
            f"destination {field_name} '{path}' has no file extension; "
            f"{dest_type} expects a {family}-family extension (e.g. {canonical}). "
            f"Add an extension to the path or change the destination type."
        )
    ext_family = _EXT_FAMILY.get(ext)
    if ext_family and ext_family != family:
        raise ValueError(
            f"destination {field_name} '{path}' ends in '{ext}' "
            f"(a {ext_family}-family extension), which does not match "
            f"destination type '{dest_type}' (expected {canonical}). "
            f"Rename the file or change the type."
        )


def _glob_extension(glob: str) -> str | None:
    """Return the last `.ext` in a glob's final path segment, or None if
    it's a directory-like pattern with no extension."""
    tail = glob.rsplit("/", 1)[-1]
    dot = tail.rfind(".")
    if dot < 0 or dot == len(tail) - 1:
        return None
    return tail[dot:].lower()


# ─── Source (SQLModel — single class serves API validation + persistence) ──
#
# `SourceBase` holds the domain fields with the two existing `@model_validator`
# methods. Both `Source(table=True)` (used by the store) and `SourceCreate`
# (used by the API) inherit them so validation fires in both code paths.
#
# `source_type` and `format` are typed as `str` / `str | None` on `SourceBase`
# so SQLModel can map them to TEXT columns without tripping on Literal[...] —
# SQLModel 0.0.x cannot resolve Literal to a SA column type. `SourceCreate`
# overrides them with the Literal types for strict validation at the API edge.
#
# `table` maps to the DB column `table_name` via sa_column so no migration is
# needed.

class SourceBase(SQLModel):
    connection_id: str
    source_type: str = SMField(sa_column=Column(Text, nullable=False))
    config: dict = SMField(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    table: str = SMField(sa_column=Column("table_name", Text, nullable=False))
    format: str | None = SMField(default=None, sa_column=Column(Text, nullable=True))

    @model_validator(mode="before")
    @classmethod
    def _extract_legacy_format(cls, data):
        """Back-compat: earlier clients put `format` inside `config`. Lift
        it to the top-level field so `_BucketSourceConfig` (extra=forbid)
        doesn't reject it during round-trip."""
        if isinstance(data, dict):
            cfg = data.get("config")
            if isinstance(cfg, dict) and "format" in cfg:
                if not data.get("format"):
                    data["format"] = cfg["format"]
                cfg = {k: v for k, v in cfg.items() if k != "format"}
                data["config"] = cfg
        return data

    @model_validator(mode="after")
    def _validate_config(self):
        model = _SOURCE_CONFIG_MODELS.get(self.source_type)
        if model is None:
            # Unknown source_type — let SourceCreate's Literal override catch it.
            return self
        # Round-trip through the typed model so extras raise + defaults fill in.
        typed = model(**self.config)
        # `by_alias=True` so `schema_` re-serialises as `schema` on the wire.
        self.config = typed.model_dump(exclude_none=True, by_alias=True)

        # Guardrail: if the user pinned a format AND the glob has an
        # extension that belongs to a different reader family, refuse.
        # Same-family mismatches (e.g. `.json` file that's actually
        # NDJSON, `format=jsonl` + `*.json`) pass through.
        if self.format and self.source_type in _FILESYSTEM_KINDS:
            glob = str(self.config.get("file_glob") or "")
            ext = _glob_extension(glob)
            ext_family = _EXT_FAMILY.get(ext) if ext else None
            fmt_family = _FORMAT_FAMILY.get(self.format)
            if ext_family and fmt_family and ext_family != fmt_family:
                raise ValueError(
                    f"file_glob '{glob}' ends in '{ext}' (a {ext_family} format), "
                    f"which does not match format '{self.format}' (a {fmt_family} "
                    f"format). Change one to match, or clear the format to auto-detect."
                )
        return self


class Source(SourceBase, table=True):
    """ORM-mapped row — persistence identity + timestamp columns.

    `table=True` bypasses Pydantic required-field checks at __init__ so ORM
    row hydration can populate instances incrementally. The validators on
    `SourceBase` still fire when a Source is constructed explicitly (e.g.
    `Source(id=..., source_type=..., ...)`) but NOT when SQLAlchemy hydrates
    a row from the DB — that is intentional (data already validated at save).
    """
    __tablename__ = "sources"

    id: str = SMField(primary_key=True)
    created_at: datetime | None = SMField(
        default=None, sa_column=Column(server_default=func.now())
    )
    updated_at: datetime | None = SMField(
        default=None,
        sa_column=Column(server_default=func.now(), onupdate=func.now()),
    )


class SourceCreate(SourceBase):
    """Strict API input — non-table so required-field checks fire.

    Overrides `source_type` and `format` with Literal types so Pydantic
    rejects unknown values at the API edge.
    """
    id: str
    source_type: SourceKind  # type: ignore[override]
    format: _FileFormat | None = None  # type: ignore[override]


# Back-compat alias — deprecated. Delete after plan 015 lands end-to-end.
DltSource = Source


# ─── Steps ────────────────────────────────────────────────────────────────

class FilterStep(BaseModel):
    op: Literal["filter"]
    expr: str

    @field_validator("expr")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(
                "filter step needs a non-empty expression — fill it in or remove the step"
            )
        return v


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

    @field_validator("expr")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(
                "map step needs a non-empty expression — fill it in or remove the step"
            )
        return v


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

    @model_validator(mode="after")
    def _validate_extension(self):
        _check_dest_path_extension(self.type, self.path)
        return self


# Back-compat alias for callers still importing the old name.
JsonFileOutput = JsonFileTarget


class CsvFileTarget(BaseModel):
    type: Literal["csv_file"]
    path: str
    fields: list[OutputField] = []

    @model_validator(mode="after")
    def _validate_extension(self):
        _check_dest_path_extension(self.type, self.path)
        return self


class ExcelFileTarget(BaseModel):
    type: Literal["excel_file"]
    path: str
    fields: list[OutputField] = []

    @model_validator(mode="after")
    def _validate_extension(self):
        _check_dest_path_extension(self.type, self.path)
        return self


class ParquetS3Target(BaseModel):
    type: Literal["parquet_s3"]
    bucket_url: str
    # `storage_options` removed — creds come from the linked s3 Connection.

    @model_validator(mode="after")
    def _validate_extension(self):
        _check_dest_path_extension(self.type, self.bucket_url, field_name="bucket_url")
        return self


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
        ExcelFileTarget,
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


# ─── Pipeline (SQLModel — single class serves API validation + persistence) ──
#
# `PipelineBase` holds the domain fields with strict Pydantic validation.
# `Pipeline` (table=True) adds the persistence identity/timestamp columns.
# `PipelineCreate` is the FastAPI input shape.
#
# Why the base + table split: SQLModel's `table=True` classes bypass Pydantic
# required-field checks at `__init__` so ORM row hydration can populate
# instances incrementally. That makes a `table=True` class unsafe as a
# FastAPI request body. `PipelineCreate` keeps validation strict at the edge.

class PipelineBase(SQLModel):
    name: str
    sources: list[str] = SMField(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    steps: list[dict] = SMField(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    output_id: str


class Pipeline(PipelineBase, table=True):
    __tablename__ = "pipelines"

    id: str = SMField(primary_key=True)
    created_at: datetime | None = SMField(
        default=None, sa_column=Column(server_default=func.now())
    )
    updated_at: datetime | None = SMField(
        default=None,
        sa_column=Column(server_default=func.now(), onupdate=func.now()),
    )


class PipelineCreate(PipelineBase):
    """Strict API input — non-table so required-field checks fire."""
    id: str


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
    "excel_file": {"local_fs"},
    "parquet_s3": {"s3"},
    "postgres": {"postgres"},
    "sql_database": {"mysql", "snowflake", "bigquery"},
}
 