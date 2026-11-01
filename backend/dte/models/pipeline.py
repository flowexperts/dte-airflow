from __future__ import annotations

import re
import uuid as _uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator
from sqlalchemy import Column, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field as SMField
from sqlmodel import SQLModel

# ─── Connections ─────────────────────────────────────────────────────────

ConnectionType = Literal[
    "local_fs",
    "s3", "gcs", "azure", "sftp",
    "postgres", "mysql", "sqlite", "mssql",
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
    ConnectionStringCredentials as _DltConnStr,
)


class _AzureSpec:
    """Local mini-spec for Azure Blob credentials.
    Accepts `connection_string` (for Azurite / custom endpoints) OR the
    standard dlt AzureCredentials fields (account_name + key/sas)."""
    _fields = (
        "azure_storage_account_name",
        "azure_storage_account_key",
        "azure_storage_sas_token",
        "connection_string",
    )

    def __init__(self, **kw):
        extra = set(kw) - set(self._fields)
        if extra:
            raise TypeError(f"unexpected azure credential keys: {sorted(extra)}")
        for k in self._fields:
            setattr(self, k, kw.get(k))
        if not self.connection_string and not self.azure_storage_account_name:
            raise TypeError(
                "azure credentials require `connection_string` or "
                "`azure_storage_account_name` + `azure_storage_account_key`/`azure_storage_sas_token`"
            )


class _GcsHmacSpec:
    """Local mini-spec: DuckDB / S3-compatible GCS uses HMAC keys, which
    dlt's `GcpServiceAccountCredentials` (JSON-key auth) can't express.
    `endpoint_url` is optional — used for fake-gcs-server in local tests."""
    _fields = ("hmac_key_id", "hmac_secret", "endpoint_url")

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
    "azure": _AzureSpec,
    "sftp": None,  # auth is the Airflow sftp provider's (plan 074)
    "postgres": _DltConnStr,
    "mysql": _DltConnStr,
    "mssql": _DltConnStr,
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


def _blank_id_means_generate(data):
    """Drop `id` when it is blank so the UUID4 `default_factory` fires.

    `default_factory` only runs when the key is ABSENT. Clients that send
    `{"id": ""}` — which every "the server will name it" form does — sail past
    it and write an empty string as the primary key. The row then exists but
    is unreachable: `GET /sources/` is not a route, and a builder slot holding
    `""` fails validation with a message about nothing being picked.

    Blank means "you name it", which is what the field's default already says.
    """
    if isinstance(data, dict):
        for key in ("id", "ID"):
            if key in data and isinstance(data[key], str) and not data[key].strip():
                data = {k: v for k, v in data.items() if k != key}
    return data


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

    _generate_blank_id = model_validator(mode="before")(
        classmethod(lambda cls, data: _blank_id_means_generate(data))
    )

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


class Connection(ConnectionBase):
    """An Airflow Connection viewed through DTE's types (plan 065).

    Not persisted here: `dte.airflow.connections.from_airflow` builds it from
    the Airflow connection, and `id` is the Airflow `conn_id`. Credentials are
    already in DTE's shape, so the dlt spec validation on `ConnectionBase`
    is skipped.
    """

    def _validate_credentials(self):  # overrides ConnectionBase's validator
        return self


# Back-compat alias — ConnectionCreate was the old 3-class name.
ConnectionCreate = ConnectionBase


# ─── Source configs (per source_type) ─────────────────────────────────────

SourceKind = Literal[
    "filesystem", "s3", "gcs", "azure", "sftp", "sql_database", "mongodb", "rest_api",
    "documents",
]
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


class SftpSourceConfig(_BucketSourceConfig):
    pass


class DocumentSourceConfig(_BucketSourceConfig):
    """A directory of documents to *list* — never to parse.

    Loading this source yields one row per file (path, filename, ext,
    size_bytes, modified_at, media_type). Extraction happens only when an
    `extract` step runs, which is what keeps `POST /api/schema/infer` instant
    and free — the builder fires it automatically on every edit.

    `format` is meaningless here: the reader family is decided per-document by
    the extract provider, not by the glob.
    """

    file_glob: str = "**/*.pdf"


class SqlDatabaseSourceConfig(BaseModel):
    """Points at a database via DuckDB scanner extension. Credentials live
    on the linked Connection (`credentials.url`). Which table is read is a
    per-pipeline-per-use decision (`SourceTableRef.table`), not part of the
    source's own config."""
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
    "sftp": SftpSourceConfig,
    "sql_database": SqlDatabaseSourceConfig,
    "mongodb": MongoDBSourceConfig,
    "rest_api": RestApiSourceConfig,
    "documents": DocumentSourceConfig,
}


_FILESYSTEM_KINDS = {"filesystem", "s3", "gcs", "azure", "sftp"}

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
    "json":    "json",
    "csv":     "csv",
    "excel":   "excel",
    "parquet": "parquet",
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

    _generate_blank_id = model_validator(mode="before")(
        classmethod(lambda cls, data: _blank_id_means_generate(data))
    )
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

        # Trim the path-ish fields. A trailing space survives copy-paste, is
        # invisible in the input, and turns a working glob into "No files
        # matched '**/*.pdf '" — an error that reads as if the pattern itself
        # were wrong. Nothing legitimate ends one of these in whitespace.
        for key in ("bucket_url", "file_glob"):
            value = self.config.get(key)
            if isinstance(value, str) and value != value.strip():
                self.config[key] = value.strip()

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

    _generate_blank_id = model_validator(mode="before")(
        classmethod(lambda cls, data: _blank_id_means_generate(data))
    )
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


CaseOp = Literal[
    "=", "!=", ">", "<", ">=", "<=", "LIKE", "IN", "IS NULL", "IS NOT NULL",
    "BETWEEN",
]


class CaseCondition(BaseModel):
    """One predicate row, mirroring the builder's condition UI.

    Structured rather than a SQL string on purpose: the compiler turns these
    into ibis expressions, so a `case` step runs on Postgres/MySQL/DuckDB
    alike. A SQL string would force the raw-SQL escape hatch, which is
    DuckDB-dialect only and is refused on every `sql_database` source.
    """
    model_config = {"extra": "forbid"}

    field: str
    op: CaseOp = "="
    # Comma-separated for IN and BETWEEN; ignored for IS [NOT] NULL.
    value: str = ""
    # How this row joins to the previous one. AND binds tighter than OR, as
    # in SQL — the compiler groups accordingly.
    join: Literal["AND", "OR"] = "AND"

    @field_validator("field")
    @classmethod
    def _field_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("case condition needs a field")
        return v


# A branch result is a plain scalar, not SQL. `None` means the branch yields
# NULL, which is a legitimate answer ("this row has no tier").
CaseValue = bool | int | float | str | None


class CaseBranch(BaseModel):
    """One WHEN/THEN arm of a `case` step."""
    model_config = {"extra": "forbid"}

    when: list[CaseCondition] = Field(min_length=1)
    then: CaseValue = None


class CaseStep(BaseModel):
    """Conditional column: if / else if / otherwise.

    Compiles to `ibis.cases`, the same portable construct the lookup step
    uses — no raw SQL, so it works on natively-bound DB sources.
    """
    op: Literal["case"]
    output_field: str
    branches: list[CaseBranch] = Field(min_length=1)
    otherwise: CaseValue = None

    @field_validator("output_field")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("case step needs an output field name")
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
    # str/list[str]: same column name on both sides (the common case).
    # dict[str, str]: left column -> right column, for a key that isn't
    # named the same on both sides (e.g. `orders.customer_id` vs
    # `customers.id`) — one entry per join column for a composite key.
    on: str | list[str] | dict[str, str]
    how: Literal["inner", "left", "right", "outer"] = "inner"
    output_id: str

    @field_validator("on")
    @classmethod
    def _on_non_empty(cls, v: str | list[str] | dict[str, str]) -> str | list[str] | dict[str, str]:
        if not v:
            raise ValueError("join step needs at least one 'on' column")
        return v


class PivotStep(BaseModel):
    op: Literal["pivot"]
    index: str | list[str]
    columns: str
    values: str
    agg: Literal["sum", "count", "avg", "min", "max"] = "sum"


class CheckStep(BaseModel):
    op: Literal["check"]
    expr: str
    label: str = ""
    severity: Literal["warn", "fail"] = "fail"

    @field_validator("expr")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(
                "check step needs a non-empty expression — fill it in or remove the step"
            )
        return v


class ProfileStep(BaseModel):
    op: Literal["profile"]
    columns: list[str] = Field(default_factory=list)


ExtractGranularity = Literal["page", "document"]


class ExtractStep(BaseModel):
    """Documents in, extracted text blocks out.

    The only op besides `join` that changes row cardinality: at `page`
    granularity one input row fans out to one row per page.

    A per-document failure fills `extract_meta.error` and leaves the output
    field NULL — it does **not** fail the run. One bad PDF in 10k must not
    cost the batch; add a downstream `check` step if you want it fatal.
    """

    op: Literal["extract"]
    # Column holding the path to read. Defaults to what a `documents` source
    # emits, so the common case needs no configuration.
    source_field: str = "path"
    provider: Literal["pypdf", "pdfplumber"] = "pdfplumber"
    granularity: ExtractGranularity = "page"
    params: dict = Field(default_factory=dict)
    output_field: str = "content"


class DataModelField(BaseModel):
    """One column the user wants extracted from a document."""

    name: str
    type: Literal["string", "int", "float", "boolean", "date", "timestamp"] = "string"
    description: str = ""
    required: bool = False
    examples: list[str] = Field(default_factory=list)
    # Only consulted by the deterministic `regex` provider.
    pattern: str | None = None


class DataModelSpec(BaseModel):
    fields: list[DataModelField]
    instructions: str = ""

    @model_validator(mode="after")
    def _validate_fields(self) -> DataModelSpec:
        if not self.fields:
            raise ValueError(
                "a structure step must declare at least one field — with none, "
                "the step produces no columns"
            )
        names = [f.name for f in self.fields]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate field names in data model: {sorted(dupes)}")
        return self


# Sampling parameters are rejected with a 400 on current Claude and OpenAI
# reasoning models. Catching them here turns a runtime failure on every single
# row into one clear validation error at save time.
_REJECTED_PARAMS = {"temperature", "top_p", "top_k"}


class StructureStep(BaseModel):
    """Extracted text in, the user's declared data model out.

    The declared fields become real typed columns. From this step onward the
    row is ordinary tabular data and every existing step — filter, join,
    aggregate, check, pivot — works on it unchanged. That is the whole point
    of splitting extract from structure.
    """

    op: Literal["structure"]
    input_field: str = "content"
    provider: Literal["claude", "openai", "regex"] = "claude"
    # Airflow connection holding the model key; None → the provider's default
    # (`anthropic_default` / `openai_default`). Ignored by regex.
    connection_id: str | None = None
    model: DataModelSpec
    params: dict = Field(default_factory=dict)
    on_error: Literal["null", "fail"] = "null"

    @model_validator(mode="after")
    def _reject_sampling_params(self) -> StructureStep:
        if "api_key" in self.params:
            raise ValueError(
                "api_key cannot be set in step params — they are stored "
                "unencrypted. Put the key in an Airflow connection and set "
                "connection_id instead"
            )
        bad = _REJECTED_PARAMS & set(self.params)
        if bad:
            raise ValueError(
                f"{sorted(bad)} are rejected with a 400 by current Claude and "
                "OpenAI reasoning models — remove them and steer with the "
                "field descriptions instead"
            )
        return self


class HttpLookupField(BaseModel):
    name: str
    # JMESPath over the JSON response, e.g. `max(urls[].upload_time)`.
    path: str
    type: Literal["string", "int", "float", "boolean", "timestamp"] = "string"


_URL_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class HttpLookupStep(BaseModel):
    """One GET per row, JSON fields out as typed columns (plan 085).

    `url` carries `{column}` placeholders filled from each row. Responses are
    cached per URL per day in the artifact store, so a preview and a run on
    the same day pay once. `max_rows` refuses to fan out over a large table:
    narrow first (filter, join), then look up.
    """

    op: Literal["http_lookup"]
    url: str
    # Airflow HTTP connection: password → `Authorization: Bearer`, plus any
    # `headers` in its extras. None → unauthenticated.
    connection_id: str | None = None
    fields: list[HttpLookupField]
    max_rows: int = Field(500, ge=1)
    on_error: Literal["null", "fail"] = "null"

    @model_validator(mode="after")
    def _validate(self) -> HttpLookupStep:
        import jmespath

        if not self.url.startswith(("http://", "https://")):
            raise ValueError(f"url must be http:// or https://, got {self.url!r}")
        for ph in _URL_PLACEHOLDER_RE.findall(self.url):
            if not _IDENT_RE.match(ph):
                raise ValueError(f"url placeholder {{{ph}}} must name a column (an identifier)")
        if not self.fields:
            raise ValueError("an http_lookup step must declare at least one field")
        names = [f.name for f in self.fields]
        bad = [n for n in names if not _IDENT_RE.match(n)]
        if bad:
            raise ValueError(f"field names must be identifiers: {bad}")
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"duplicate field names: {dupes}")
        for f in self.fields:
            try:
                jmespath.compile(f.path)
            except jmespath.exceptions.JMESPathError as e:
                raise ValueError(f"field {f.name!r}: invalid JMESPath {f.path!r}: {e}") from None
        return self


class OutputField(BaseModel):
    field: str
    alias: str | None = None


# ─── Output targets (slimmed — creds live on the Connection) ──────────────
#
# Format and location are independent axes.  A target names the *format*
# only; where the bytes land is carried by `path`, which may be a local
# path or an object-store URI (`s3://`, `gcs://`, `az://`).  The writer
# picks its DuckDB extension and SECRET from the URI scheme.
#
# These used to be one class per format-and-location pair (`json_file` was
# local-only, `parquet_s3` was S3-only).  The legacy discriminator values
# are still accepted on read — see `_LEGACY_DEST_TYPES`.

class _FileTarget(BaseModel):
    """Shared shape: a format discriminator plus a destination `path`."""
    path: str
    fields: list[OutputField] = []

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_type(cls, data):
        """Let direct construction use the pre-rename spelling.

        `JsonFileTarget(type="json_file", …)` still works — the alias would
        otherwise resolve to `JsonTarget` and reject its own old literal.
        Union dispatch is handled separately by `_canonicalise_dest_type`,
        since the discriminator is read before any validator runs.
        """
        return _canonicalise_dest_type(data)

    @model_validator(mode="after")
    def _validate_extension(self):
        _check_dest_path_extension(self.type, self.path)
        return self


class JsonTarget(_FileTarget):
    type: Literal["json"]


class CsvTarget(_FileTarget):
    type: Literal["csv"]


class ExcelTarget(_FileTarget):
    type: Literal["excel"]


class ParquetTarget(_FileTarget):
    type: Literal["parquet"]
    # `bucket_url` was the field name back when this was `parquet_s3`.
    model_config = {"populate_by_name": True}
    path: str = Field(validation_alias=AliasChoices("path", "bucket_url"))


# Back-compat aliases — kept for one release so existing imports keep working.
JsonFileTarget = JsonTarget
CsvFileTarget = CsvTarget
ExcelFileTarget = ExcelTarget
ParquetS3Target = ParquetTarget
JsonFileOutput = JsonTarget


# Persisted `destinations.config->>'type'` values that predate the rename.
# Alembic 028 rewrites them, but rows written by an older node (or a
# rolled-back deploy) still arrive with the old spelling.
_LEGACY_DEST_TYPES: dict[str, str] = {
    "json_file": "json",
    "csv_file": "csv",
    "excel_file": "excel",
    "parquet_s3": "parquet",
}


def _canonicalise_dest_type(config):
    """Rewrite a legacy `type` discriminator in a raw config dict.

    Returns the input untouched for anything already canonical, or for
    non-dicts (an already-parsed target instance).
    """
    if not isinstance(config, dict):
        return config
    legacy = _LEGACY_DEST_TYPES.get(config.get("type"))
    if legacy is None:
        return config
    return {**config, "type": legacy}


class PostgresTarget(BaseModel):
    type: Literal["postgres"]
    schema_: str = Field(alias="schema")
    table: str
    write_disposition: Literal["replace", "append", "merge"] = "replace"
    model_config = {"populate_by_name": True}


class SqlDatabaseTarget(BaseModel):
    type: Literal["sql_database"]
    dialect: Literal["mysql", "mssql", "snowflake", "bigquery"]
    schema_: str = Field(alias="schema")
    table: str
    write_disposition: Literal["replace", "append", "merge"] = "replace"
    model_config = {"populate_by_name": True}


OutputTarget = Annotated[
    JsonTarget | CsvTarget | ExcelTarget | ParquetTarget | PostgresTarget | SqlDatabaseTarget,
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

    _generate_blank_id = model_validator(mode="before")(
        classmethod(lambda cls, data: _blank_id_means_generate(data))
    )
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
            raw = _canonicalise_dest_type(self.config)
            self.config = adapter.validate_python(raw)  # type: ignore[assignment]
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
            raw = _canonicalise_dest_type(self.config)
            object.__setattr__(self, "config", adapter.validate_python(raw))
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
    ("case", None): CaseStep,
    ("check", None): CheckStep,
    ("profile", None): ProfileStep,
    ("extract", None): ExtractStep,
    ("structure", None): StructureStep,
    ("http_lookup", None): HttpLookupStep,
}


EngineChoice = Literal[
    "auto",
    "duckdb", "postgres", "mysql", "mssql", "sqlite", "bigquery", "snowflake", "trino",
]


# ─── Pipeline inputs (trigger-time typed params) ─────────────────────────

import re as _re

ParamType = Literal["string", "int", "float", "date", "timestamp", "boolean"]

_PARAM_NAME_RE = _re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


_ALIAS_RE = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _sanitize_alias(source_id: str) -> str:
    """Derive a valid alias from a bare source id for the back-compat
    shorthand (`sources: ["id", ...]`). Source ids default to a UUID4
    (`3fa85f64-5717-...`), which contains hyphens and can start with a
    digit — neither is a valid alias. Non-identifier characters become
    `_`; a leading digit gets a `_` prefix. Collisions between two
    sanitized UUIDs are not a practical concern (they differ in their hex
    digits, which sanitizing preserves)."""
    sanitized = _re.sub(r"[^A-Za-z0-9_]", "_", source_id)
    if not sanitized or sanitized[0].isdigit():
        sanitized = f"_{sanitized}"
    return sanitized


class SourceTableRef(BaseModel):
    """One use of a `Source` within a pipeline.

    `alias` is how joins and the compiler's table registry refer to this
    use — it replaces the bare source id as the registry key, which is what
    lets the same `sql_database` Source be picked more than once (against
    different tables) in one pipeline. `table` is required when the
    resolved source is `sql_database` (there is no default table on the
    source anymore) and forbidden for every other kind, where the source's
    own config already names what it loads.
    """
    model_config = {"extra": "forbid"}

    source_id: str
    table: str | None = None
    alias: str

    @field_validator("alias")
    @classmethod
    def _valid_alias(cls, v: str) -> str:
        if not v or not _ALIAS_RE.match(v):
            raise ValueError(
                f"alias {v!r} must be non-empty and match [A-Za-z_][A-Za-z0-9_]*"
            )
        return v


def coerce_source_refs(sources: list) -> list[SourceTableRef]:
    """Normalise a pipeline's `sources` list to typed `SourceTableRef`s.

    Three shapes reach this: a bare source id string (back-compat
    shorthand, also what a `table=True` `Pipeline` built via direct
    construction in tests still holds — SQLModel skips validators there),
    a raw dict (what a store-hydrated `Pipeline` holds — ORM hydration
    skips validators too), and an already-typed `SourceTableRef` (a
    validated `PipelineBase` body). Call sites that need
    `.source_id`/`.table`/`.alias` should route through this rather than
    assume the type.
    """
    out: list[SourceTableRef] = []
    for s in sources:
        if isinstance(s, SourceTableRef):
            out.append(s)
        elif isinstance(s, dict):
            out.append(SourceTableRef.model_validate(s))
        elif isinstance(s, str):
            out.append(SourceTableRef(source_id=s, alias=_sanitize_alias(s)))
        else:
            raise TypeError(f"unexpected source ref type: {type(s).__name__}")
    return out


OverlapPolicy = Literal["skip", "allow"]


class PipelineSchedule(BaseModel):
    """A pipeline's one recurring trigger (plan 068), embedded in the spec.

    `cron_expr`/`timezone`, `params` and `eval_set_id` are validated at the
    API layer (`routes/pipelines._validate_schedule`) — each needs something
    this model doesn't have (a clock, the pipeline's declared params, the
    eval-set store). Airflow does the firing: the pipeline's one DAG gets
    this cron (`dte.airflow.dag_factory`).
    """
    cron_expr: str
    timezone: str = "UTC"
    params: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    overlap: OverlapPolicy = "skip"
    # The corpus a scheduled *eval* run scores against; required for eval
    # pipelines, since a nightly eval run with no corpus scores nothing.
    eval_set_id: str | None = None
    # On failure (plan 070). Retries default off: a retry after a partial
    # append writes rows twice, so `validate_schedule` refuses them there.
    retries: int = Field(0, ge=0, le=10)
    retry_delay_s: int = Field(300, ge=10)
    timeout_s: int | None = Field(None, ge=60)


NotifyEvent = Literal["failure", "success", "retry"]


class PipelineNotification(BaseModel):
    """One Airflow notifier fired on run events (plan 070), manual or scheduled.

    `notifier` is the class path of any notifier an installed provider
    registers; `params` are its constructor kwargs, and templated ones may use
    `{{ dte_message }}`. Checked against the registry at save
    (`dte.airflow.notify.problem`).
    """
    notifier: str
    params: dict[str, Any] = Field(default_factory=dict)
    on: list[NotifyEvent] = Field(default_factory=lambda: ["failure"], min_length=1)


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
        from dte.compiler.interpolate import ParamValidationError, coerce_param_value
        try:
            coerce_param_value(self.default, self.type)
        except ParamValidationError as e:
            raise ValueError(f"default for {self.name!r} does not parse as {self.type}: {e}")
        return self


# The pipeline types that write nowhere. `quality` reports contract results,
# `eval` scores against labels, `viz` feeds a dashboard tile off `preview` —
# none of the three reaches a writer, so none needs an `output_id`.
#
# This is one function because it used to be five copies of the same tuple
# in `dte/api/routes/pipelines.py` (validate, engine-compat, trigger,
# dry-run, preview). A type added to four of the five saves cleanly and then
# 422s on the fifth, which is the endpoint nobody tests by hand.
_OUTPUTLESS_PIPELINE_TYPES = ("quality", "eval", "viz")


def pipeline_requires_output(pipeline) -> bool:
    """True when this pipeline must name a destination that exists.

    Takes anything with a `pipeline_type` — `PipelineBase`, `Pipeline`, or a
    revision snapshot — and treats a missing attribute as `transform`, which
    is the historical shape of rows written before the field existed.
    """
    ptype = getattr(pipeline, "pipeline_type", "transform") or "transform"
    return ptype not in _OUTPUTLESS_PIPELINE_TYPES


class PipelineBase(SQLModel):
    """API/domain fields.

    Identity: `id` is server-generated (UUID4 by default). `name` is the
    editable, unique-per-tenant label — required from day one.
    """

    # Same guard every other named entity carries. Pipelines were the one
    # holdout, so `{"id": ""}` wrote an empty-string primary key: the row
    # listed fine and was then unreachable, because `/api/pipelines/` is not
    # a route and `DELETE` on it 307s. Only SQL could remove it. It stayed
    # hidden because the builder strips `id` before posting, so it
    # reproduced only from the API.
    _generate_blank_id = model_validator(mode="before")(
        classmethod(lambda cls, data: _blank_id_means_generate(data))
    )
    id: str = SMField(default_factory=lambda: str(_uuid.uuid4()))
    name: str
    sources: list[SourceTableRef] = SMField(default_factory=list)
    steps: list[dict] = SMField(default_factory=list)
    output_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_bare_source_ids(cls, data):
        """Back-compat shorthand: `sources: ["src_id", ...]` is accepted and
        expanded to `[{"source_id": "src_id", "alias": "src_id"}, ...]` —
        the alias defaults to the source id. A `sql_database` source used
        this way has no `table`, which `_validate_pipeline_refs` (the
        route layer, which can see the source's kind) then rejects — this
        validator only reshapes, it never validates against source kind."""
        if not isinstance(data, dict):
            return data
        sources = data.get("sources")
        if not isinstance(sources, list):
            return data
        data["sources"] = [
            {"source_id": s, "alias": _sanitize_alias(s)} if isinstance(s, str) else s
            for s in sources
        ]
        return data
    # Engine dispatch.  Default "auto" derives the engine from the pipeline's
    # source composition: single-source postgres → runs in postgres,
    # filesystem-only → DuckDB, mixed → DuckDB (or 422 with hint to use
    # trino when DuckDB can't federate).  Legacy values "duckdb"/"trino"
    # remain accepted as explicit overrides.
    engine: EngineChoice = "auto"
    # "viz" feeds a dashboard tile: it is compiled and previewed, never
    # written. See `pipeline_requires_output` for the three types that
    # share that property and the one place they are named.
    pipeline_type: Literal["transform", "quality", "eval", "viz"] = "transform"
    quality_contracts: list = SMField(default_factory=list)  # list[Contract] — typed by validator
    # The comparison this eval pipeline expands to: dotted axis path → values
    # to vary, e.g. {"provider": ["claude", "regex"]}. Absent means N=1 — an
    # ordinary single-config eval run, which is what a nightly regression
    # check schedules and so stays first-class.
    #
    # Stored rather than posted per-launch (plan 055). While it lived only in
    # the Compare wizard a comparison could not be reopened, adjusted and
    # re-run: you started from an empty form and minted a fresh set of variant
    # pipelines every time.
    matrix: dict[str, list] | None = None
    # Declared trigger-time inputs. Referenced from filter/map expressions as
    # {{params.<name>}}; validated against declared types on trigger.
    params: list[PipelineParam] = SMField(default_factory=list)
    tenant_id: str = "default"
    # At most one schedule: a pipeline is one DAG and a DAG has one schedule
    # (plan 068). Part of the spec, so a schedule edit is a revision.
    schedule: PipelineSchedule | None = None
    # Separate from the schedule: manual runs notify too (plan 070).
    notifications: list[PipelineNotification] = SMField(default_factory=list)

    @model_validator(mode="after")
    def _validate_matrix(self):
        """A comparison matrix belongs to an eval pipeline, and its axes must
        be ones a sweep could actually apply.

        Both halves refuse rather than ignore. A matrix on a transform
        pipeline would be stored and silently do nothing; an axis nothing
        reads would expand to N identical cells that look like proof the
        setting makes no difference.
        """
        if self.matrix is None:
            return self
        if self.pipeline_type != "eval":
            raise ValueError(
                "only an eval pipeline carries a comparison matrix; this one "
                f"is {self.pipeline_type!r}. Convert it first "
                "(POST /api/pipelines/{id}/as-eval)."
            )
        # Imported here, not at module scope: the authority for what a sweep
        # can apply lives in dte.evals, which is a layer above models.
        from dte.evals.sweep import validate_matrix_axes

        validate_matrix_axes(self.steps, self.matrix)
        return self

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
            if self.pipeline_type == "quality" and step["op"] in ("aggregate", "pivot"):
                raise ValueError(
                    f"Step op {step['op']!r} is not allowed in quality pipelines"
                )
        if self.pipeline_type == "eval" and not any(
            isinstance(s, dict) and s.get("op") == "structure" for s in self.steps
        ):
            # Scoring compares the declared fields of a data model against
            # labels. Without a structure step there are no such columns, so
            # the run would complete and score a flat zero — a failure that
            # reads as "the extractor is bad" rather than "the pipeline is
            # misconfigured". Fail at save instead.
            raise ValueError(
                "an eval pipeline needs a 'structure' step — it is the step "
                "that produces the fields being scored"
            )
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
            SYSTEM_VAR_NAMES,
            extract_param_refs,
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
    # Untyped `list` (not `list[dict]`) — like `quality_contracts` below,
    # this avoids a Pydantic serializer warning when a test (or the legacy
    # bare-id shorthand pre-coercion) constructs a table=True `Pipeline`
    # directly with plain source-id strings, which `table=True`
    # construction doesn't run through `_coerce_bare_source_ids` to fix up.
    sources: list = SMField(  # type: ignore[override]
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
    pipeline_type: str = SMField(  # type: ignore[override]
        default="transform", sa_column=Column(Text, nullable=False, server_default="transform")
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
    # Nullable with no default: "no matrix" (a single-config eval run) must
    # stay distinguishable from "an empty matrix" — the same rule the eval
    # columns on `runs` follow.
    matrix: dict[str, list] | None = SMField(  # type: ignore[override]
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    schedule: dict | None = SMField(  # type: ignore[override]
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    notifications: list = SMField(  # type: ignore[override]
        default_factory=list, sa_column=Column(JSONB, nullable=False, server_default="[]")
    )
    created_at: datetime | None = SMField(
        default=None, sa_column=Column(server_default=func.now())
    )
    updated_at: datetime | None = SMField(
        default=None,
        sa_column=Column(server_default=func.now(), onupdate=func.now()),
    )

    # Strict in, lenient out.
    #
    # `PipelineBase` — what POST/PUT bind — parses every step through its
    # op-specific model, so bad input is still rejected at save. This class
    # is the *response* model, and FastAPI re-validates it on every read.
    # Running the same strict check there means a row written by a newer
    # build (or by a branch since rolled back) raises inside response
    # validation and takes down `GET /api/pipelines` **for every pipeline in
    # the list**, not just that one. Version skew is normal; losing the whole
    # collection to one row from the future is not.
    #
    # Still enforced: a step is a dict and names an op. A step that isn't
    # shaped like a step is corruption, not skew. An unknown op — or known
    # params this build dislikes — is reported by the compiler against the
    # individual step, which is where it can be acted on.
    #
    # `mode="before"`, not "after": an after-validator on a table=True class
    # touches instrumented attributes, and under `model_validate` the
    # instance has no `_sa_instance_state` yet. Reading the raw payload
    # sidesteps that entirely.
    @model_validator(mode="before")
    @classmethod
    def _validate_steps(cls, data):
        if not isinstance(data, dict):
            return data
        for i, step in enumerate(data.get("steps") or []):
            if not isinstance(step, dict) or "op" not in step:
                raise ValueError(f"steps[{i}]: missing 'op' key")
        return data


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
    "sftp": {"sftp"},
    "sql_database": {"postgres", "mysql", "mssql", "sqlite", "snowflake", "bigquery"},
    "mongodb": {"mongodb"},
    "rest_api": {"rest_api"},
    # Documents live wherever files live. Only local_fs has a loader today;
    # the object-store kinds are listed so a saved source doesn't have to be
    # re-pointed when the remote listing lands.
    "documents": {"local_fs", "s3", "gcs", "azure"},
}

# File formats are location-agnostic: each writes to a local path or to any
# object store, so they bind to any file-shaped connection.
_FILE_DEST_CONNECTIONS: set[ConnectionType] = {"local_fs", "s3", "gcs", "azure", "sftp"}

DESTINATION_CONNECTION_COMPAT: dict[str, set[ConnectionType]] = {
    "json": _FILE_DEST_CONNECTIONS,
    "csv": _FILE_DEST_CONNECTIONS,
    "excel": _FILE_DEST_CONNECTIONS,
    "parquet": _FILE_DEST_CONNECTIONS,
    "postgres": {"postgres"},
    # Shape-level: `sql_database` destinations *may* bind to any SQL-family
    # connection. Runtime-level: whether the active engine has a writer for
    # that specific dialect is enforced by ENGINE_WRITE_SUPPORT below.
    "sql_database": {"mysql", "mssql", "snowflake", "bigquery"},
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
    "duckdb", "postgres", "mysql", "mssql", "sqlite", "bigquery", "snowflake", "trino",
]

ENGINE_READ_SUPPORT: dict[EngineName, set[ConnectionType]] = {
    "duckdb":    {"local_fs", "s3", "gcs", "azure", "sftp", "mongodb", "rest_api"},
    "postgres":  {"postgres"},
    "mysql":     {"mysql"},
    "mssql":     {"mssql"},
    "sqlite":    {"sqlite"},
    "bigquery":  {"bigquery"},
    "snowflake": {"snowflake"},
    "trino":     {"postgres", "mysql", "sqlite", "snowflake", "bigquery",
                  "s3", "gcs", "azure"},
}

# Writers currently implemented in `dte/engine/writers/*.py`:
# - local_fs / s3 / gcs / azure / sftp: json, csv, excel, parquet — all four
#   formats go through DuckDB's `COPY … TO`, writing object-store URIs through
#   the connection's Airflow provider filesystem (see `writers/_copy.py`).
# - postgres: postgres writer (via dlt[postgres])
# - mysql / snowflake / bigquery: dlt writer extras (optional)
#
# Every engine can reach every file target: `writers/_copy.py` streams a
# non-DuckDB result through Arrow into a scratch DuckDB connection before
# COPY, so file/object-store outputs are not limited to DuckDB pipelines.
_FILE_WRITE_TARGETS: set[ConnectionType] = {"local_fs", "s3", "gcs", "azure", "sftp"}

ENGINE_WRITE_SUPPORT: dict[EngineName, set[ConnectionType]] = {
    "duckdb":    _FILE_WRITE_TARGETS | {"postgres", "mysql", "mssql"},
    "postgres":  _FILE_WRITE_TARGETS | {"postgres"},
    "mysql":     _FILE_WRITE_TARGETS | {"mysql"},
    "mssql":     _FILE_WRITE_TARGETS | {"mssql"},
    "sqlite":    _FILE_WRITE_TARGETS | {"sqlite"},
    "bigquery":  _FILE_WRITE_TARGETS | {"bigquery"},
    "snowflake": _FILE_WRITE_TARGETS | {"snowflake"},
    "trino":     _FILE_WRITE_TARGETS | {"postgres", "mysql", "snowflake", "bigquery"},
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
    destination: tuple[str, ConnectionType] | None,
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

    bad_dest = None
    if destination is not None:
        dest_id, dest_ctype = destination
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
