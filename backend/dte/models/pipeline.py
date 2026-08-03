from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import Column, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field as SMField
from sqlmodel import SQLModel

from dte.secrets.encrypted_json import EncryptedJSON

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
)
from dlt.common.configuration.specs import (
    AzureCredentials as _DltAzure,
)
from dlt.common.configuration.specs import (
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


# ─── Connection ───────────────────────────────────────────────────────────────
#
# Two-class shape:
#   ConnectionBase — API/domain fields + credential validator.  `id: str`
#       required here so FastAPI raises 422 on missing.  `connection_type`
#       uses the strict `ConnectionType` Literal for API-edge validation;
#       the table class overrides it with `str` because SQLModel 0.0.x
#       can't map a Literal to a TEXT column.
#   Connection(table=True) — persistence identity + EncryptedJSON column.
#       Encryption/decryption happens inside the TypeDecorator; the store
#       needs NO SecretResolver — `credentials` is a real mapped column.

class ConnectionBase(SQLModel):
    """API/domain fields.  `credentials` is validated against the dlt spec
    class for the given `connection_type` and stored as a cleaned dict.

    Identity model
    --------------
    - `id`: opaque, server-generated (default: UUID4 string). Clients that
      omit it get a fresh one; clients that supply it (legacy migration
      scripts, historic tests) keep working. Never edited after creation.
    - `name`: user-facing label, editable, unique per (tenant_id, class).
      If omitted at construction we default to `id` so historic call
      sites (e.g. `ConnectionBase(id="local_fs", ...)`) still round-trip.
    """

    id: str = SMField(default_factory=lambda: str(_uuid.uuid4()))
    name: str | None = None
    connection_type: ConnectionType  # strict Literal for API validation
    credentials: dict = SMField(default_factory=dict)
    tenant_id: str = "default"

    @model_validator(mode="after")
    def _default_name_to_id(self):
        if not self.name:
            self.name = self.id
        return self

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


class Connection(ConnectionBase, table=True):
    """ORM-mapped row.

    SQLModel 0.0.39 cannot map Literal[...] to a SA column, so
    `connection_type` is overridden as plain `str` with an explicit
    `sa_column`.  `credentials` is backed by `EncryptedJSON` (BYTEA) —
    encrypt/decrypt happen transparently at the TypeDecorator level.
    """
    __tablename__ = "connections"

    # Override id to declare it as the primary key.
    id: str = SMField(  # type: ignore[override]
        default_factory=lambda: str(_uuid.uuid4()), primary_key=True
    )
    # Editable, unique-per-tenant display name. NOT NULL at the DB layer
    # (see migration 020); nullable here so back-compat callers that only
    # pass `id` still construct — `_default_name_to_id` fills it in on Base
    # and we mirror the same fallback in stores.
    name: str | None = SMField(  # type: ignore[override]
        default=None, sa_column=Column(Text, nullable=False)
    )
    # Override: Literal → str for SQLAlchemy mapping.
    connection_type: str = SMField(  # type: ignore[override]
        sa_column=Column(Text, nullable=False)
    )
    # Real mapped column — replaces the legacy `credentials_encrypted` BYTEA.
    # Physical column name kept as `credentials_encrypted` so no migration needed.
    credentials: dict = SMField(  # type: ignore[override]
        default_factory=dict,
        sa_column=Column("credentials_encrypted", EncryptedJSON, nullable=False),
    )
    tenant_id: str = SMField(  # type: ignore[override]
        default="default", sa_column=Column(Text, nullable=False, server_default="default")
    )
    created_at: datetime | None = SMField(
        default=None, sa_column=Column(server_default=func.now())
    )
    updated_at: datetime | None = SMField(
        default=None,
        sa_column=Column(server_default=func.now(), onupdate=func.now()),
    )


# Back-compat alias — ConnectionCreate was the old 3-class name.
ConnectionCreate = ConnectionBase


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


# ─── Source ──────────────────────────────────────────────────────────────────
#
# Two-class shape:
#   SourceBase — API/domain fields + validators.  `source_type` uses the
#       strict `SourceKind` Literal; `format` uses `_FileFormat | None`.
#       `id: str` required so FastAPI raises 422 on missing.
#   Source(table=True) — persistence identity + timestamp columns.
#       `source_type` and `format` are overridden as `str` / `str | None`
#       so SQLModel maps them to TEXT without tripping on Literal.
#       `table` maps to `table_name` column (no migration needed).

class SourceBase(SQLModel):
    """API/domain fields + config validators.

    `source_type` is the strict `SourceKind` Literal for API validation.
    `format` is the strict `_FileFormat | None` Literal.

    Identity: `id` is server-generated (UUID4 by default). `name` is the
    editable, unique-per-tenant label; defaults to `id` when omitted so
    historic callers keep working.
    """
    id: str = SMField(default_factory=lambda: str(_uuid.uuid4()))
    name: str | None = None
    connection_id: str
    source_type: SourceKind  # strict Literal for API validation
    config: dict = SMField(default_factory=dict)
    table: str
    format: _FileFormat | None = None
    tenant_id: str = "default"

    @model_validator(mode="after")
    def _default_name_to_id(self):
        if not self.name:
            self.name = self.id
        return self

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
            # Unknown source_type — let the Literal type annotation catch it.
            return self
        # Round-trip through the typed model so extras raise + defaults fill in.
        typed = model(**self.config)
        # `by_alias=True` so `schema_` re-serialises as `schema` on the wire.
        self.config = typed.model_dump(exclude_none=True, by_alias=True)

        # Guardrail: if the user pinned a format AND the glob has an
        # extension that belongs to a different reader family, refuse.
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

    SQLModel 0.0.39 cannot map Literal[...] to a SA column, so
    `source_type` and `format` are overridden as plain `str` / `str | None`
    with explicit `sa_column` declarations.  `table` maps to the DB column
    `table_name` (no migration needed).

    `table=True` bypasses Pydantic required-field checks at __init__ so
    ORM row hydration can populate instances incrementally.  Validators on
    `SourceBase` still fire for explicit construction (e.g. in routes that
    build `Source(**base.model_dump())`), but NOT when SQLAlchemy hydrates
    a row from the DB — that is intentional (data already validated at save).
    """
    __tablename__ = "sources"

    # Override id to declare it as the primary key.
    id: str = SMField(  # type: ignore[override]
        default_factory=lambda: str(_uuid.uuid4()), primary_key=True
    )
    name: str | None = SMField(  # type: ignore[override]
        default=None, sa_column=Column(Text, nullable=False)
    )
    # Override: Literal → str for SQLAlchemy mapping.
    source_type: str = SMField(  # type: ignore[override]
        sa_column=Column(Text, nullable=False)
    )
    config: dict = SMField(  # type: ignore[override]
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    table: str = SMField(  # type: ignore[override]
        sa_column=Column("table_name", Text, nullable=False)
    )
    format: str | None = SMField(  # type: ignore[override]
        default=None, sa_column=Column(Text, nullable=True)
    )
    tenant_id: str = SMField(  # type: ignore[override]
        default="default", sa_column=Column(Text, nullable=False, server_default="default")
    )
    created_at: datetime | None = SMField(
        default=None, sa_column=Column(server_default=func.now())
    )
    updated_at: datetime | None = SMField(
        default=None,
        sa_column=Column(server_default=func.now(), onupdate=func.now()),
    )


# Back-compat alias — SourceCreate was the old 3-class name.
SourceCreate = SourceBase

# Back-compat alias for callers still importing the old name.
DltSource = Source


# ─── LookupTable ───────────────────────────────────────────────────────────
# First-class reusable lookup mapping. Referenced from map/lookup steps by id
# so the same table can be shared across many pipelines. Inline `table` dicts
# on lookup steps are gone; use `scripts/migrate_extract_lookups.py` to migrate
# legacy pipelines.

class LookupTableBase(SQLModel):
    """API/domain fields.

    Identity: `id` is server-generated (UUID4 by default). `name` is the
    editable, unique-per-tenant label; defaults to `id` when omitted so
    historic callers keep working.
    """
    id: str = SMField(default_factory=lambda: str(_uuid.uuid4()))
    name: str | None = None
    mappings: dict[str, str] = SMField(default_factory=dict)
    default: str | None = None
    tenant_id: str = "default"

    @model_validator(mode="after")
    def _default_name_to_id(self):
        if not self.name:
            self.name = self.id
        return self


class LookupTable(LookupTableBase, table=True):
    __tablename__ = "lookup_tables"

    id: str = SMField(  # type: ignore[override]
        default_factory=lambda: str(_uuid.uuid4()), primary_key=True
    )
    name: str | None = SMField(default=None, sa_column=Column(Text, nullable=False))
    mappings: dict = SMField(  # type: ignore[override]
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    default: str | None = SMField(default=None, sa_column=Column(Text, nullable=True))
    tenant_id: str = SMField(  # type: ignore[override]
        default="default", sa_column=Column(Text, nullable=False, server_default="default")
    )
    created_at: datetime | None = SMField(
        default=None, sa_column=Column(server_default=func.now())
    )
    updated_at: datetime | None = SMField(
        default=None,
        sa_column=Column(server_default=func.now(), onupdate=func.now()),
    )


LookupTableCreate = LookupTableBase


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
    """Applies a saved LookupTable to a column.

    The mapping table itself lives in the `lookup_tables` store (referenced by
    `lookup_id`). At compile time the caller resolves the id → LookupTable and
    passes them to `compile_pipeline(..., lookup_tables=...)`.
    """
    model_config = {"extra": "forbid"}

    op: Literal["map"]
    mode: Literal["lookup"]
    field: str
    lookup_id: str
    output_field: str | None = None


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


DatePart = Literal["year", "quarter", "month", "week", "day", "date", "dow", "hour"]


class DatePartGroupBy(BaseModel):
    """Group by a date/timestamp field extracted to a component (year, month, ...).

    Emitted column defaults to `<field>_<part>` unless `alias` is provided.
    """
    field: str
    part: DatePart
    alias: str | None = None


class AggregateStep(BaseModel):
    op: Literal["aggregate"]
    group_by: list[str | DatePartGroupBy]
    aggregations: list[AggSpec]


class SelectStep(BaseModel):
    op: Literal["select"]
    fields: list[OutputField] = []
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
    JsonFileTarget | CsvFileTarget | ExcelFileTarget | ParquetS3Target | PostgresTarget | SqlDatabaseTarget,
    Field(discriminator="type"),
]


# ─── Destination ─────────────────────────────────────────────────────────────
#
# Two-class shape:
#   DestinationBase — API/domain fields.  `config: dict` declared for JSONB
#       mapping, narrowed to the typed OutputTarget union by `_narrow_config`
#       at validation time.  `id: str` required so FastAPI raises 422 on
#       missing.
#   Destination(table=True) — persistence identity + timestamp columns.
#       Validators on Base are bypassed at ORM hydration time (table=True
#       skips them), so the store calls `narrow_config()` explicitly.

class DestinationBase(SQLModel):
    """API/domain fields — no persistence identity.

    `connection_id` references a Connection row.
    `config` is declared as `dict` for SQLModel JSONB mapping, but is narrowed
    to the typed `OutputTarget` union by `_narrow_config` at validation time.

    Identity: `id` is server-generated (UUID4 by default). `name` is the
    editable, unique-per-tenant label; defaults to `id` when omitted so
    historic callers keep working.
    """
    id: str = SMField(default_factory=lambda: str(_uuid.uuid4()))
    name: str | None = None
    connection_id: str
    config: dict = SMField(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    tenant_id: str = "default"

    @model_validator(mode="after")
    def _default_name_to_id(self):
        if not self.name:
            self.name = self.id
        return self

    @model_validator(mode="after")
    def _narrow_config(self) -> DestinationBase:
        """Parse raw dict config into the typed OutputTarget discriminated union.

        Runs after ORM hydration (where SQLAlchemy gives back a raw dict from JSONB)
        and after direct construction. Writers and the compiler receive a typed
        instance with real attribute access — no dict key lookups at call sites."""
        if isinstance(self.config, dict) and self.config:
            from pydantic import TypeAdapter
            adapter = TypeAdapter(OutputTarget)
            self.config = adapter.validate_python(self.config)  # type: ignore[assignment]
        return self

    def to_api_dict(self) -> dict:
        """Serialise for API responses: id + name + connection_id + config as plain dict."""
        cfg = self.config
        if hasattr(cfg, "model_dump"):
            cfg_dict = cfg.model_dump(by_alias=True, exclude_none=True)
        else:
            cfg_dict = cfg  # already a plain dict (edge case)
        return {
            "id": self.id,
            "name": self.name or self.id,
            "connection_id": self.connection_id,
            "config": cfg_dict,
        }


class Destination(DestinationBase, table=True):
    """ORM-mapped row. `dest_type` mirrors `config.type` and is written at save
    time by the store (denormalised column — drop in a follow-up migration).

    IMPORTANT: SQLModel's `table=True` bypasses Pydantic model validators on
    __init__, so `_narrow_config` does NOT auto-run after ORM hydration. The
    store calls `row.narrow_config()` explicitly after fetching from the DB.
    """
    __tablename__ = "destinations"

    # Override id to declare it as the primary key.
    id: str = SMField(  # type: ignore[override]
        default_factory=lambda: str(_uuid.uuid4()), primary_key=True
    )
    name: str | None = SMField(  # type: ignore[override]
        default=None, sa_column=Column(Text, nullable=False)
    )
    config: dict = SMField(  # type: ignore[override]
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    dest_type: str = SMField(sa_column=Column(Text, nullable=False))
    tenant_id: str = SMField(  # type: ignore[override]
        default="default", sa_column=Column(Text, nullable=False, server_default="default")
    )
    created_at: datetime | None = SMField(
        default=None, sa_column=Column(server_default=func.now())
    )
    updated_at: datetime | None = SMField(
        default=None,
        sa_column=Column(server_default=func.now(), onupdate=func.now()),
    )

    def narrow_config(self) -> Destination:
        """Parse raw dict `config` into the typed OutputTarget union in-place.

        Must be called explicitly by the store after ORM hydration because
        `table=True` classes bypass model validators at __init__ time."""
        if isinstance(self.config, dict) and self.config:
            from pydantic import TypeAdapter
            adapter = TypeAdapter(OutputTarget)
            # Use object.__setattr__ to bypass SQLAlchemy's instrumented
            # attribute machinery.
            object.__setattr__(self, "config", adapter.validate_python(self.config))
        return self

# Back-compat alias — DestinationCreate was the old 3-class name.
DestinationCreate = DestinationBase


# ─── Pipeline ─────────────────────────────────────────────────────────────────
#
# Two-class shape:
#   PipelineBase — API/domain fields.  `id: str` required so FastAPI raises
#       422 on missing.
#   Pipeline(table=True) — persistence identity + JSONB columns +
#       timestamp columns.

_STEP_MODELS: dict[tuple[str, str | None], type[BaseModel]] = {
    ("filter", None): FilterStep,
    ("rename", None): RenameStep,
    ("retype", None): RetypeStep,
    ("map", "lookup"): LookupMapStep,
    ("map", "expression"): ExpressionMapStep,
    ("map", "calculation"): ExpressionMapStep,
    ("sort", None): SortStep,
    ("aggregate", None): AggregateStep,
    ("select", None): SelectStep,
    ("join", None): JoinStep,
    ("pivot", None): PivotStep,
}


EngineChoice = Literal[
    "auto",
    "duckdb", "postgres", "mysql", "sqlite", "bigquery", "snowflake", "trino",
]


# ─── Pipeline inputs (trigger-time typed params) ─────────────────────────

import re as _re

ParamType = Literal["string", "int", "float", "date", "timestamp", "boolean"]

_PARAM_NAME_RE = _re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class PipelineParam(BaseModel):
    """Declared trigger-time input on a pipeline.

    Referenced from filter/map expressions as ``{{params.<name>}}``. Values
    are supplied on the trigger request body and validated against the
    declared ``type`` before interpolation.
    """
    model_config = {"extra": "forbid"}

    name: str
    type: ParamType
    required: bool = True
    default: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        if not _PARAM_NAME_RE.match(v):
            raise ValueError(
                f"param name {v!r} must match [a-zA-Z_][a-zA-Z0-9_]*"
            )
        return v

    @model_validator(mode="after")
    def _default_parses(self):
        # Treat empty string as "no default" — the builder sends this when
        # the user hasn't filled the Default input, and it wouldn't parse as
        # a typed value anyway.
        if self.default == "":
            object.__setattr__(self, "default", None)
        if self.description == "":
            object.__setattr__(self, "description", None)
        if self.default is None:
            return self
        # Late import — coercion helper lives in the compiler package and we
        # want to avoid a top-level compiler import inside models.
        from dte.compiler.interpolate import coerce_param_value, ParamValidationError
        try:
            coerce_param_value(self.default, self.type)
        except ParamValidationError as e:
            raise ValueError(f"default for {self.name!r} does not parse as {self.type}: {e}")
        return self


class PipelineBase(SQLModel):
    """API/domain fields.

    Identity: `id` is server-generated (UUID4 by default). `name` is the
    editable, unique-per-tenant label — required from day one.
    """
    id: str = SMField(default_factory=lambda: str(_uuid.uuid4()))
    name: str
    sources: list[str] = SMField(default_factory=list)
    steps: list[dict] = SMField(default_factory=list)
    output_id: str
    # Engine dispatch.  Default "auto" derives the engine from the pipeline's
    # source composition: single-source postgres → runs in postgres,
    # filesystem-only → DuckDB, mixed → DuckDB (or 422 with hint to use
    # trino when DuckDB can't federate).  Legacy values "duckdb"/"trino"
    # remain accepted as explicit overrides.
    engine: EngineChoice = "auto"
    quality_contracts: list = SMField(default_factory=list)  # list[Contract] — typed by validator
    # Declared trigger-time inputs. Referenced from filter/map expressions as
    # {{params.<name>}}; validated against declared types on trigger.
    params: list[PipelineParam] = SMField(default_factory=list)
    tenant_id: str = "default"

    @model_validator(mode="after")
    def _validate_steps(self):
        # steps is list[dict] (map's mode-discriminator prevents a typed Union).
        # Dispatch each step through its op-specific model so per-step validators
        # (e.g. SelectStep._check_exclusive) fire at API save time instead of at
        # trigger-time compile.
        for i, step in enumerate(self.steps):
            if not isinstance(step, dict) or "op" not in step:
                raise ValueError(f"steps[{i}]: missing 'op' key")
            key = (step["op"], step.get("mode") if step["op"] == "map" else None)
            model = _STEP_MODELS.get(key)
            if model is None:
                raise ValueError(
                    f"steps[{i}]: unknown op/mode combination {key!r}"
                )
            model.model_validate(step)
        return self

    @model_validator(mode="after")
    def _validate_params_and_refs(self):
        """Unique param names + every {{params.X}} reference is declared."""
        # SQLModel table=True skips this same-named validator on ORM hydration
        # only when quality_contracts logic runs first — this validator is
        # idempotent so re-running it on hydration is safe.
        raw = self.params or []
        # `params` may still be raw dicts if constructed through SQLModel ORM
        # hydration; coerce them here so downstream code sees typed instances.
        coerced: list[PipelineParam] = []
        for p in raw:
            if isinstance(p, PipelineParam):
                coerced.append(p)
            elif isinstance(p, dict):
                coerced.append(PipelineParam.model_validate(p))
            else:
                raise ValueError(f"params entry must be dict or PipelineParam, got {type(p).__name__}")
        seen: set[str] = set()
        for p in coerced:
            if p.name in seen:
                raise ValueError(f"duplicate pipeline param: {p.name!r}")
            seen.add(p.name)
        object.__setattr__(self, "params", coerced)

        # Ref check — every {{params.X}} in a filter/map expr must resolve.
        from dte.compiler.interpolate import (
            extract_param_refs,
            SYSTEM_VAR_NAMES,
        )
        declared = {p.name for p in coerced}
        for i, step in enumerate(self.steps or []):
            op = step.get("op")
            if op not in ("filter", "map"):
                continue
            expr = step.get("expr")
            if not isinstance(expr, str):
                continue
            refs = extract_param_refs(expr)
            for path in refs:
                if path in SYSTEM_VAR_NAMES:
                    continue
                if not path.startswith("params."):
                    raise ValueError(
                        f"steps[{i}]: unknown variable {{{{{path}}}}} "
                        f"— must be one of params.* or {sorted(SYSTEM_VAR_NAMES)}"
                    )
                name = path.split(".", 1)[1]
                if name not in declared:
                    raise ValueError(
                        f"steps[{i}]: {{{{params.{name}}}}} references undeclared input"
                        f" — declare it under Inputs or fix the name"
                    )
        return self

    @model_validator(mode="after")
    def _validate_quality_contracts(self):
        """Parse quality_contracts dicts into typed Contract instances."""
        if not self.quality_contracts:
            return self
        from pydantic import TypeAdapter
        from dte.models.quality import Contract
        ta = TypeAdapter(list[Contract])  # type: ignore[type-arg]
        raw = self.quality_contracts
        # If entries are already typed instances (e.g. from test construction), keep them.
        if all(hasattr(c, "type") and not isinstance(c, dict) for c in raw):
            return self
        # Otherwise validate from dicts.
        parsed = ta.validate_python([c if isinstance(c, dict) else c.model_dump() for c in raw])
        object.__setattr__(self, "quality_contracts", parsed)
        return self


class Pipeline(PipelineBase, table=True):
    __tablename__ = "pipelines"

    # Override id to declare it as the primary key.
    id: str = SMField(  # type: ignore[override]
        default_factory=lambda: str(_uuid.uuid4()), primary_key=True
    )
    # Override list fields with explicit JSONB sa_columns.
    sources: list[str] = SMField(  # type: ignore[override]
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    steps: list[dict] = SMField(  # type: ignore[override]
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    # SQLModel 0.0.39 can't map Literal[...] to a TEXT column — override
    # with plain str + explicit sa_column.  Strict Literal stays on Base.
    engine: str = SMField(  # type: ignore[override]
        default="duckdb", sa_column=Column(Text, nullable=False, server_default="duckdb")
    )
    quality_contracts: list = SMField(  # type: ignore[override]
        default_factory=list, sa_column=Column(JSONB, nullable=False, server_default="'[]'::jsonb")
    )
    params: list = SMField(  # type: ignore[override]
        default_factory=list, sa_column=Column(JSONB, nullable=False, server_default="'[]'::jsonb")
    )
    tenant_id: str = SMField(  # type: ignore[override]
        default="default", sa_column=Column(Text, nullable=False, server_default="default")
    )
    created_at: datetime | None = SMField(
        default=None, sa_column=Column(server_default=func.now())
    )
    updated_at: datetime | None = SMField(
        default=None,
        sa_column=Column(server_default=func.now(), onupdate=func.now()),
    )


# Back-compat alias — PipelineCreate was the old 3-class name.
PipelineCreate = PipelineBase


class PipelineRevisionBase(SQLModel):
    """One immutable snapshot of a pipeline. Written after every accepted
    POST/PUT on `/api/pipelines*`. `config` is the full serialised
    `PipelineBase.model_dump()` at write time — enough to reconstruct the
    exact spec a run was compiled against.
    """
    id: str
    pipeline_id: str
    config: dict = SMField(default_factory=dict)
    changed_by: str | None = None
    summary: str | None = None


class PipelineRevision(PipelineRevisionBase, table=True):
    __tablename__ = "pipeline_revisions"

    id: str = SMField(primary_key=True)  # type: ignore[override]
    config: dict = SMField(  # type: ignore[override]
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    changed_at: datetime | None = SMField(
        default=None, sa_column=Column(server_default=func.now())
    )


# ─── Connection ↔ Source/Destination compatibility ────────────────────────
# Which connection_types a given source_type / destination type may bind to.
# Enforced in the API save layer (needs the connection lookup).

SOURCE_CONNECTION_COMPAT: dict[str, set[ConnectionType]] = {
    "filesystem": {"local_fs"},
    "s3": {"s3"},
    "gcs": {"gcs"},
    "azure": {"azure"},
    "sql_database": {"postgres", "mysql", "sqlite", "snowflake", "bigquery"},
    "mongodb": {"mongodb"},
    "rest_api": {"rest_api"},
}

DESTINATION_CONNECTION_COMPAT: dict[str, set[ConnectionType]] = {
    "json_file": {"local_fs"},
    "csv_file": {"local_fs"},
    "excel_file": {"local_fs"},
    "parquet_s3": {"s3"},
    "postgres": {"postgres"},
    # Shape-level: `sql_database` destinations *may* bind to any SQL-family
    # connection. Runtime-level: whether the active engine has a writer for
    # that specific dialect is enforced by ENGINE_WRITE_SUPPORT below.
    "sql_database": {"mysql", "snowflake", "bigquery"},
}


# ─── Engine × connection-type capability matrix ──────────────────────────
# Which connection types each engine can READ and WRITE.  Enforced by
# `validate_pipeline_engine_compat` at pipeline create/update/trigger.
#
# The rows here are grounded in what the code actually implements today:
# - `duckdb` reads filesystem-family via native readers, and mongodb /
#   rest_api via dlt hops that land in DuckDB.  It does NOT natively read
#   postgres/mysql/sqlite anymore — those route through their own ibis
#   backends (see `BackendRegistry.for_connection`).
# - `postgres`/`mysql`/`sqlite`/`bigquery`/`snowflake` are "pushdown"
#   engines — a single-source pipeline whose source is one of those
#   connection types runs entirely in that source database.
# - `trino` federates across many connectors; useful when a pipeline mixes
#   sources that ibis can't join natively (e.g. snowflake ⨝ filesystem).

EngineName = Literal[
    "duckdb", "postgres", "mysql", "sqlite", "bigquery", "snowflake", "trino",
]

ENGINE_READ_SUPPORT: dict[EngineName, set[ConnectionType]] = {
    "duckdb":    {"local_fs", "s3", "gcs", "azure", "mongodb", "rest_api"},
    "postgres":  {"postgres"},
    "mysql":     {"mysql"},
    "sqlite":    {"sqlite"},
    "bigquery":  {"bigquery"},
    "snowflake": {"snowflake"},
    "trino":     {"postgres", "mysql", "sqlite", "snowflake", "bigquery",
                  "s3", "gcs", "azure"},
}

# Writers currently implemented in `dte/engine/writers/*.py`:
# - local_fs: json_file / csv_file / excel_file
# - s3: parquet_s3
# - postgres: postgres writer (via dlt[postgres])
# - mysql / snowflake / bigquery: dlt writer extras (optional)
ENGINE_WRITE_SUPPORT: dict[EngineName, set[ConnectionType]] = {
    "duckdb":    {"local_fs", "s3", "postgres", "mysql"},
    "postgres":  {"postgres", "local_fs"},
    "mysql":     {"mysql", "local_fs"},
    "sqlite":    {"sqlite", "local_fs"},
    "bigquery":  {"bigquery", "local_fs"},
    "snowflake": {"snowflake", "local_fs"},
    "trino":     {"postgres", "mysql", "snowflake", "bigquery",
                  "s3", "gcs", "azure"},
}


def resolve_pipeline_engine(
    engine_choice: str,
    source_connection_types: list[ConnectionType],
) -> EngineName:
    """Resolve an ``engine`` field value to a concrete engine name.

    Rules:

    1. Explicit engine (`"duckdb"`, `"trino"`, `"postgres"` …) → return as-is.
    2. `"auto"` (or missing) →
       - all sources land on DuckDB-family (filesystem, s3, gcs, azure,
         mongodb, rest_api) → ``duckdb``
       - all sources share a single non-DuckDB connection type (e.g. every
         source is postgres) → that engine (pushdown)
       - mixed → ``duckdb`` if every source can be read by DuckDB, else the
         caller must switch to Trino explicitly.  This function returns
         ``duckdb`` optimistically; the compatibility validator raises when
         DuckDB can't actually read every source.
    """
    if engine_choice and engine_choice != "auto":
        return engine_choice  # type: ignore[return-value]

    types = set(source_connection_types)
    if not types:
        return "duckdb"

    duckdb_native = ENGINE_READ_SUPPORT["duckdb"]
    if types <= duckdb_native:
        return "duckdb"

    # Single non-DuckDB dialect across all sources → pushdown to that engine.
    non_duckdb = types - duckdb_native
    if len(non_duckdb) == 1 and types.issubset(duckdb_native | non_duckdb):
        # If sources also include filesystem-family, we can't push down —
        # fall back to duckdb (which will then fail engine compat if the
        # non-duckdb type isn't readable via duckdb).
        if types & duckdb_native:
            return "duckdb"
        (single,) = non_duckdb
        if single in ENGINE_READ_SUPPORT:
            return single  # type: ignore[return-value]

    return "duckdb"


class EngineIncompatible(Exception):
    """Raised when a pipeline's chosen engine can't handle every source or
    destination it references.  Route handlers turn this into a 422 with a
    structured payload."""

    def __init__(
        self,
        code: str,
        engine: str,
        incompatible_sources: list[dict] | None = None,
        incompatible_destination: dict | None = None,
        message: str = "",
    ):
        self.code = code
        self.engine = engine
        self.incompatible_sources = incompatible_sources or []
        self.incompatible_destination = incompatible_destination
        super().__init__(message or code)

    def payload(self) -> dict:
        return {
            "code": self.code,
            "engine": self.engine,
            "incompatible_sources": self.incompatible_sources,
            "incompatible_destination": self.incompatible_destination,
        }


def validate_pipeline_engine_compat(
    engine: str,
    sources: list[tuple[str, ConnectionType]],
    destination: tuple[str, ConnectionType],
) -> None:
    """Raise :class:`EngineIncompatible` if ``engine`` can't read every
    source or write to the destination.

    Parameters
    ----------
    engine
        Resolved engine name (already run through :func:`resolve_pipeline_engine`).
    sources
        List of ``(source_id, connection_type)`` tuples.
    destination
        ``(destination_id, connection_type)`` tuple.
    """
    reads = ENGINE_READ_SUPPORT.get(engine, set())
    writes = ENGINE_WRITE_SUPPORT.get(engine, set())

    bad_sources = [
        {
            "source_id": sid,
            "connection_type": ctype,
            "reason": (
                f"{engine!r} engine cannot read {ctype!r} sources. "
                f"Supported: {sorted(reads)}. "
                "Switch pipeline engine or split the source out."
            ),
        }
        for sid, ctype in sources
        if ctype not in reads
    ]

    dest_id, dest_ctype = destination
    bad_dest = None
    if dest_ctype not in writes:
        bad_dest = {
            "destination_id": dest_id,
            "connection_type": dest_ctype,
            "reason": (
                f"{engine!r} engine cannot write to {dest_ctype!r} destinations. "
                f"Supported: {sorted(writes)}."
            ),
        }

    if bad_sources or bad_dest:
        raise EngineIncompatible(
            code="engine_incompatible",
            engine=engine,
            incompatible_sources=bad_sources,
            incompatible_destination=bad_dest,
        )
