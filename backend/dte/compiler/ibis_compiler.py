from __future__ import annotations

import functools
import json
import operator
import re
from typing import TYPE_CHECKING

import ibis
import ibis.expr.datatypes as dt

from dte.compiler.dialect_notes import execution_dialect_of
from dte.errors import CompilerError
from dte.models.pipeline import (
    ExtractStep,
    StructureStep,
    AggregateStep,
    CaseStep,
    CaseCondition,
    DatePartGroupBy,
    ExpressionMapStep,
    FilterStep,
    JoinStep,
    LookupMapStep,
    LookupTable,
    OutputField,
    Pipeline,
    PivotStep,
    RenameStep,
    RetypeStep,
    SelectStep,
    SortStep,
    coerce_source_refs,
)

if TYPE_CHECKING:
    from dte.engine.base import BaseEngine


class MixedBackendError(CompilerError):
    """Raised when a pipeline's source tables span multiple ibis backends.

    Ibis can't execute a join across two live backends without materialising
    one side.  In the DTE architecture, sources on the same Connection.id
    share a backend (via :class:`BackendRegistry`), so a pipeline with two
    postgres tables on the same connection is fine, but joining a postgres
    table with a filesystem CSV (or with a bigquery table) trips this
    error.  Fix: split into two pipelines, or opt into ``engine="trino"``
    to federate.
    """

    def __init__(self, source_backends: dict[str, str]):
        self.source_backends = source_backends
        engines = sorted(set(source_backends.values()))
        super().__init__(
            f"Pipeline sources span multiple ibis backends ({engines}). "
            "Cross-backend joins aren't supported without a federator. "
            "Split into single-backend pipelines, or set engine='trino'."
        )

_TYPE_MAP: dict[str, dt.DataType] = {
    "string": dt.String(),
    "int": dt.Int64(),
    "float": dt.Float64(),
    "boolean": dt.Boolean(),
    "date": dt.Date(),
    "timestamp": dt.Timestamp(),
}


def _check_single_backend(tables: dict[str, ibis.Table]) -> None:
    """Reject pipelines whose source tables live on more than one ibis
    backend.  See :class:`MixedBackendError` for the rationale.

    Tables from the same connection share a backend instance (BackendRegistry
    guarantees this by caching), so identity comparison via ``id(backend)`` is
    reliable — no false positives from two DuckDB connections that look alike.
    """
    if not tables:
        return
    per_source: dict[str, tuple[int, str]] = {}
    for sid, tbl in tables.items():
        backend = tbl._find_backend()
        per_source[sid] = (id(backend), type(backend).__name__)
    unique = {bid for bid, _ in per_source.values()}
    if len(unique) > 1:
        raise MixedBackendError({sid: name for sid, (_, name) in per_source.items()})


def _resolve_field(table: ibis.Table, field_path: str) -> ibis.Expr:
    parts = field_path.split(".")
    if parts[0] in table.columns:
        col = table[parts[0]]
        for part in parts[1:]:
            col = col[part]
        return col
    dlt_name = "__".join(parts)
    if dlt_name in table.columns:
        return table[dlt_name]
    if field_path in table.columns:
        return table[field_path]
    raise CompilerError(
        f"unknown field {field_path!r}; available columns: {sorted(table.columns)}"
    )


# Columns the product depends on rather than the user: `artifact_ref` points
# at the source document, `extract_meta.key` at the cached parse holding the
# word boxes, `structure_meta` at per-field provenance, `block_index` at the
# position within the document.
#
# A user `select` cannot drop these. None of them is interesting to look at,
# so the natural tidy-up removes them — and that silently destroys the ability
# to verify the output, because the columns that make a row checkable are
# exactly the ones that read as noise. A projection says which *data* to carry
# forward, not whether the row remembers where it came from.
#
# This is retention through projection only, not a global invariant: an
# `aggregate` collapses rows and the refs stop meaning anything, so they go.
SYSTEM_COLUMNS = frozenset(
    {"artifact_ref", "extract_meta", "structure_meta", "block_index"}
)


def compile_pipeline(
    pipeline: Pipeline,
    tables: dict[str, ibis.Table],
    output=None,
    lookup_tables: dict[str, LookupTable] | None = None,
    on_step=None,
    engine: BaseEngine | None = None,
    on_step_schema=None,
    on_step_sql=None,
    on_quality_result=None,  # Callable[[int, QualityResult], None] | None
    on_enrichment_stats=None,  # Callable[[int, dict], None] | None
) -> ibis.Table:
    """Compile a pipeline into an ibis expression.

    `on_step(step_index, op, status, message=None)` — optional sync callback
    invoked with `status="started"` before each step and `status="completed"`
    or `status="failed"` after. Callers use this to persist per-step events
    without threading async into the compiler.

    `engine` — optional engine instance (plan-034).  When supplied, raw-SQL
    escape hatches (filter / expression-map) are routed through
    ``engine.apply_filter_sql`` / ``engine.apply_expression_sql`` so the
    engine can apply backend-specific behaviour (e.g. Trino rejecting raw
    DuckDB SQL).  When ``None`` (default) the existing ``table._find_backend()``
    path is used — backwards-compatible for all existing callers.

    `on_step_schema(step_index, columns)` — optional sync callback fired
    after each step compiles successfully with the list of column names
    on the current-key table.  Feeds ``/api/pipelines/step-schemas`` so
    the frontend can offer autocomplete on aggregation aliases and pivot
    outputs downstream (plan 038 item 7).

    `on_step_sql(step_index, sql)` — optional sync callback fired after
    each step compiles successfully with the SQL that materialises the
    current-key table.  SQL is rendered via ``ibis.to_sql`` using the
    engine's dialect (defaulting to ``duckdb`` when no engine is
    supplied).  Feeds the preview SQL panel (plan-039).
    """
    registry = dict(tables)
    _check_single_backend(registry)
    lookups = lookup_tables or {}
    source_refs = coerce_source_refs(pipeline.sources)
    current_key = source_refs[0].alias

    def _emit(idx, op, status, msg=None):
        if on_step is not None:
            try:
                on_step(idx, op, status, msg)
            except Exception:  # never let telemetry crash a run
                pass

    for idx, step in enumerate(pipeline.steps):
        op = step["op"]
        _emit(idx, op, "started")
        try:
            if op == "join":
                s = JoinStep(**step)
                result = _apply_join(registry[s.left], registry[s.right], s)
                registry[s.output_id] = result
                current_key = s.output_id
            else:
                table = registry[current_key]
                table = _dispatch_single_table_step(
                    table, step, lookups, engine=engine,
                    idx=idx, on_quality_result=on_quality_result,
                    on_step_sql=on_step_sql,
                    on_enrichment_stats=on_enrichment_stats,
                )
                registry[current_key] = table
        except Exception as e:
            _emit(idx, op, "failed", str(e))
            raise
        _emit(idx, op, "completed")
        if on_step_schema is not None:
            try:
                cols = list(registry[current_key].columns)
                on_step_schema(idx, cols)
            except Exception:  # never let telemetry crash a run
                pass
        # check/profile steps call on_step_sql themselves with the actual check SQL;
        # for all other ops capture the resulting table expression.
        if on_step_sql is not None and op not in ("check", "profile"):
            try:
                # The TABLE's dialect, not the engine's. DuckDBEngine always
                # reports "duckdb", so a pipeline reading Postgres used to
                # render Postgres-bound SQL as DuckDB — a panel showing a
                # query that never runs.
                sql = str(ibis.to_sql(
                    registry[current_key],
                    dialect=execution_dialect_of(registry[current_key]),
                ))
                on_step_sql(idx, sql)
            except Exception:  # never let telemetry crash a run
                pass

    result = registry[current_key]
    fields = getattr(output, "fields", None)
    if fields:
        result = _apply_output_fields(result, fields)
    return result


def _dispatch_single_table_step(
    table: ibis.Table,
    step: dict,
    lookup_tables: dict[str, LookupTable],
    engine: BaseEngine | None = None,
    idx: int = 0,
    on_quality_result=None,
    on_step_sql=None,
    on_enrichment_stats=None,
) -> ibis.Table:
    op = step["op"]
    if op == "filter":
        return _apply_filter(table, FilterStep(**step), engine=engine)
    elif op == "rename":
        return _apply_rename(table, RenameStep(**step))
    elif op == "retype":
        return _apply_retype(table, RetypeStep(**step))
    elif op == "map":
        mode = step["mode"]
        if mode == "lookup":
            return _apply_lookup(table, LookupMapStep(**step), lookup_tables)
        else:
            return _apply_expression(table, ExpressionMapStep(**step), engine=engine)
    elif op == "sort":
        return _apply_sort(table, SortStep(**step))
    elif op == "aggregate":
        return _apply_aggregate(table, AggregateStep(**step))
    elif op == "case":
        return _apply_case(table, CaseStep(**step))
    elif op == "pivot":
        return _apply_pivot(table, PivotStep(**step))
    elif op == "select":
        s = SelectStep(**step)
        if s.drop:
            # System columns are exempt from a drop. Drop mode is the more
            # dangerous of the two: the builder derives the keep-set from the
            # schema, so a user who never typed `artifact_ref` still strips it.
            drop_set = set(s.drop) - SYSTEM_COLUMNS
            keep = [c for c in table.columns if c not in drop_set]
            return table.select(keep)
        return _apply_output_fields(table, s.fields, keep_system=True)
    elif op == "check":
        return _apply_check_step(table, step, idx=idx, engine=engine,
                                 on_quality_result=on_quality_result,
                                 on_step_sql=on_step_sql)
    elif op == "profile":
        return _apply_profile(table, step, idx=idx, engine=engine,
                              on_quality_result=on_quality_result)
    elif op == "extract":
        return _apply_extract(table, ExtractStep(**step), engine=engine, idx=idx)
    elif op == "structure":
        return _apply_structure(
            table, StructureStep(**step), engine=engine, idx=idx,
            on_enrichment_stats=on_enrichment_stats,
        )
    raise CompilerError(f"unknown step op {op!r}")


def _apply_structure(
    table: ibis.Table,
    step: "StructureStep",
    engine: "BaseEngine | None" = None,
    idx: int = 0,
    on_enrichment_stats=None,
) -> ibis.Table:
    """Turn extracted text into the user's declared typed columns.

    Materialises, like every enrichment step. Each declared field becomes a
    real column; alongside them `structure_meta` carries per-field provenance
    so the inspector can show *where* a value came from.

    Cached on the hash of the input text plus the full config, so two
    documents whose pages contain identical text share one call, and re-running
    an unchanged pipeline costs nothing.
    """
    import hashlib

    from dte.artifacts import derived_key, get_artifact_store
    from dte.engine.base import EnrichmentSpec
    from dte.providers import structure_provider
    from dte.providers.base import Block, DataModel, FieldSpec

    if engine is None:
        raise CompilerError("structure steps require an engine")

    provider = structure_provider(step.provider)
    store = get_artifact_store()

    data_model = DataModel(
        fields=[FieldSpec(**f.model_dump()) for f in step.model.fields],
        instructions=step.model.instructions,
    )
    # Everything that changes the answer is in the key: the declared model
    # (names, types, descriptions all steer the model) and the call params.
    config = {"model": step.model.model_dump(), "params": step.params}

    stats = {"calls": 0, "cached": 0, "errors": 0,
             "input_tokens": 0, "output_tokens": 0}

    def _structure_model(step) -> str:
        """The model that actually served the call, for per-row pricing.

        `params["model"]` when set, else the provider's default. Recorded
        per row rather than per run because a sweep varies it, and a run
        priced against the wrong model is a wrong bill.
        """
        explicit = (step.params or {}).get("model")
        if explicit:
            return str(explicit)
        return getattr(provider, "_default_model", "") or step.provider

    def _mapper(row: dict) -> list[dict]:
        text = row.get(step.input_field)
        blank = {f.name: None for f in step.model.fields}

        if not text or not str(text).strip():
            return [{**blank, "structure_meta": json.dumps({
                "provider": step.provider, "cached": False,
                "error": f"no text in {step.input_field!r}", "ms": 0, "fields": {},
            })}]

        key = derived_key(
            hashlib.sha256(str(text).encode("utf-8")).hexdigest(),
            "structure", step.provider, config,
        )

        if store.exists(key):
            payload = json.loads(store.get(key).decode("utf-8"))
            stats["cached"] += 1
            meta = {"provider": step.provider, "cached": True,
                    "error": payload.get("error"), "ms": 0,
                    # Zero tokens is the literal truth on a cache hit: no
                    # call was made. That is what makes the cache visible
                    # in the run's cost rather than merely asserted.
                    "input_tokens": 0, "output_tokens": 0,
                    "model": _structure_model(step),
                    "fields": payload.get("provenance", {})}
            return [{**payload["values"], "structure_meta": json.dumps(meta, default=str)}]

        result = provider.structure(
            [Block(text=str(text), index=0, page=row.get("page"))],
            data_model, step.params,
        )
        stats["calls"] += 1
        stats["input_tokens"] += result.input_tokens
        stats["output_tokens"] += result.output_tokens
        if result.error:
            stats["errors"] += 1
            # `on_error="fail"` turns a per-row problem into a run-level one —
            # opt-in, because the default of carrying on is right far more often.
            if step.on_error == "fail":
                raise CompilerError(
                    f"structure step {idx} failed on a row: {result.error}"
                )

        # A failure is a property of the attempt, not of the input. Caching
        # one turns a missing key, a 429 or a five-minute outage into a
        # permanent property of that document: every later run *hits* the
        # cache, calls nothing, costs nothing, and returns the same nulls —
        # so fixing the cause changes nothing and the config reads as
        # permanently incapable. Worse, it reports as a clean, fast,
        # zero-cost abstention, which is indistinguishable from a model that
        # looked and found nothing.
        if result.error is None:
            store.put(
                key,
                json.dumps({"values": result.values, "provenance": result.provenance,
                            "error": None}, default=str).encode("utf-8"),
                "application/json",
            )
        return [{
            **result.values,
            "structure_meta": json.dumps({
                "provider": step.provider, "cached": False,
                "error": result.error, "ms": result.elapsed_ms,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "model": _structure_model(step),
                "fields": result.provenance,
            }, default=str),
        }]

    _SQL_TYPE = {"string": "VARCHAR", "int": "BIGINT", "float": "DOUBLE",
                 "boolean": "BOOLEAN", "date": "VARCHAR", "timestamp": "VARCHAR"}
    out_schema = {f.name: _SQL_TYPE.get(f.type, "VARCHAR") for f in step.model.fields}
    out_schema["structure_meta"] = "VARCHAR"  # JSON-encoded; see _mapper

    result_table = engine.apply_enrichment(
        table,
        EnrichmentSpec(name=f"structure_{idx}", mapper=_mapper,
                       output_schema=out_schema),
    )

    if on_enrichment_stats is not None:
        try:
            on_enrichment_stats(idx, {**stats, "provider": step.provider})
        except Exception:  # never let telemetry crash a run
            pass
    return result_table


def _apply_extract(
    table: ibis.Table,
    step: "ExtractStep",
    engine: "BaseEngine | None" = None,
    idx: int = 0,
) -> ibis.Table:
    """Read each document and emit its text blocks.

    Unlike every other step this **materialises** — see `EnrichmentSpec`. It
    also fans out: at `page` granularity one input row becomes one row per
    page.

    Results are cached in the artifact store under
    `sha256(doc_bytes | op | provider | params)`, so a re-run costs nothing and
    a later `structure` prompt change never re-parses a PDF. Two files with
    identical bytes share one cache entry.
    """
    from dte.artifacts import derived_key, doc_key, get_artifact_store
    from dte.engine.base import EnrichmentSpec
    from dte.providers import extract_provider

    if engine is None:
        raise CompilerError("extract steps require an engine")

    provider = extract_provider(step.provider)
    store = get_artifact_store()
    # Everything that changes the answer must change the key. `_v` covers the
    # stored *shape*: v1 payloads dropped `words`, so a v1 hit would serve the
    # inspector blocks it can never draw boxes from. Bumping busts them, and
    # re-extraction is local CPU — nothing billable is re-paid.
    cache_params = {"granularity": step.granularity, "_v": 2, **step.params}

    def _mapper(row: dict) -> list[dict]:
        path = row.get(step.source_field)
        meta = {"provider": step.provider, "ms": 0, "cached": False,
                "error": None, "key": None}

        try:
            with open(path, "rb") as fh:
                content = fh.read()
        except OSError as exc:
            # A file that vanished between listing and extraction is one bad
            # row, not a failed run.
            meta["error"] = f"could not read {path!r}: {exc}"
            return [_row(step, None, 0, None, None, meta)]

        dk = doc_key(content)
        key = derived_key(dk, "extract", step.provider, cache_params)

        # Every row below carries `artifact://<dk>`, so the bytes behind that
        # ref have to exist. This sits *outside* the cache branch on purpose:
        # a cache written before this code — or one whose documents were
        # evicted — would otherwise never heal, because the derived-key hit
        # short-circuits past the only write.
        if not store.exists(dk):
            store.put(dk, content, row.get("media_type") or "application/pdf")

        meta["key"] = key

        if store.exists(key):
            payload = json.loads(store.get(key).decode("utf-8"))
            meta.update(cached=True, error=payload.get("error"))
            blocks = payload["blocks"]
        else:
            result = provider.extract(
                content,
                row.get("media_type") or "application/pdf",
                {"granularity": step.granularity, **step.params},
            )
            blocks = [
                # `words` is what turns a char span into a rectangle. It is by
                # far the largest part of the payload and the only reason the
                # inspector can highlight rather than merely quote.
                {"text": b.text, "index": b.index, "page": b.page,
                 "bbox": b.bbox, "words": b.words,
                 "width": b.width, "height": b.height}
                for b in result.blocks
            ]
            meta.update(ms=result.elapsed_ms, error=result.error)
            # Same rule as `structure`: never cache a failure. A PDF that
            # failed to parse because the file was briefly unreadable must
            # be retried, not remembered as unparseable forever.
            if result.error is None:
                store.put(
                    key,
                    json.dumps({"blocks": blocks, "error": None}).encode("utf-8"),
                    "application/json",
                )

        if not blocks:
            return [_row(step, None, 0, None, f"artifact://{dk}", meta)]
        return [
            _row(step, b["text"], b["index"], b["page"], f"artifact://{dk}", meta)
            for b in blocks
        ]

    return engine.apply_enrichment(
        table,
        EnrichmentSpec(
            name=f"extract_{idx}",
            mapper=_mapper,
            output_schema={
                step.output_field: "VARCHAR",
                "block_index": "BIGINT",
                "page": "BIGINT",
                "artifact_ref": "VARCHAR",
                "extract_meta": "JSON",
            },
        ),
    )


def _row(step, text, index, page, ref, meta) -> dict:
    return {
        step.output_field: text,
        "block_index": index,
        "page": page,
        "artifact_ref": ref,
        "extract_meta": meta,
    }


def _apply_join(left: ibis.Table, right: ibis.Table, step: JoinStep) -> ibis.Table:
    if isinstance(step.on, dict):
        # left column -> right column — the key isn't named the same on
        # both sides (e.g. `orders.customer_id` vs `customers.id`).
        predicates = [left[l] == right[r] for l, r in step.on.items()]
    else:
        on_cols = [step.on] if isinstance(step.on, str) else step.on
        predicates = [left[c] == right[c] for c in on_cols]
    # ibis suffixes duplicate column names with _right when both tables share the same column name
    return left.join(right, predicates, how=step.how)


def _apply_pivot(table: ibis.Table, step: PivotStep) -> ibis.Table:
    # `Table.pivot_wider` compiles to a portable GROUP BY + FILTER(WHERE ...)
    # aggregate, unlike DuckDB's PIVOT statement (raw dialect SQL — unusable
    # against the native postgres/mysql/sqlite backends plan 056 loads
    # sql_database sources through). Stays a lazy ibis expression; no
    # raw-connection materialisation required.
    index_cols = [step.index] if isinstance(step.index, str) else step.index
    return table.pivot_wider(
        id_cols=ibis.selectors.cols(*index_cols),
        names_from=step.columns,
        values_from=step.values,
        values_agg=step.agg,
    )


def _apply_check_step(
    table: ibis.Table,
    step: dict,
    idx: int = 0,
    engine: "BaseEngine | None" = None,
    on_quality_result=None,
    on_step_sql=None,
) -> ibis.Table:
    """Assert a SQL condition holds for all rows.

    Counts rows where NOT (expr) — violations. Returns the table unchanged.
    Calls on_quality_result(idx, QualityResult) if the callback is provided.
    """
    import uuid as _uuid
    from dte.models.quality import QualityResult

    expr = step.get("expr", "")
    severity = step.get("severity", "fail")
    label = step.get("label") or expr

    if engine is None:
        return table

    view_name = f"__check_v_{idx}__"
    sql = ibis.to_sql(table)
    engine.con.con.execute(f"CREATE OR REPLACE TEMP VIEW {view_name} AS {sql}")
    if on_step_sql is not None:
        try:
            on_step_sql(idx, f"SELECT * FROM {view_name} WHERE NOT ({expr})")
        except Exception:
            pass
    try:
        violation_count = engine.con.con.execute(
            f"SELECT COUNT(*) FROM {view_name} WHERE NOT ({expr})"
        ).fetchone()[0]
        total = engine.con.con.execute(
            f"SELECT COUNT(*) FROM {view_name}"
        ).fetchone()[0]
        passed = violation_count == 0
        detail = f"{violation_count}/{total} rows failed: {label}" if not passed else None
        result = QualityResult(
            contract_id=str(_uuid.uuid4()),
            contract_type="check",
            label=label,
            passed=passed,
            severity=severity,
            detail=detail,
        )
        if on_quality_result is not None:
            on_quality_result(idx, result)
    finally:
        try:
            engine.con.con.execute(f"DROP VIEW IF EXISTS {view_name}")
        except Exception:
            pass
    return table


def _apply_profile(
    table: ibis.Table,
    step: dict,
    idx: int,
    engine,
    on_quality_result,
) -> ibis.Table:
    """Profile columns, call on_quality_result for each, return table unchanged."""
    from dte.models.quality import QualityResult
    import uuid as _uuid_mod
    import json as _json

    if engine is None:
        return table

    con = engine.con
    columns = list(step.get("columns") or [])
    view_name = f"__profile_v_{idx}__"
    sql_str = ibis.to_sql(table)
    con.con.execute(f"CREATE OR REPLACE TEMP VIEW {view_name} AS {sql_str}")

    try:
        if not columns:
            schema_result = con.con.execute(
                f"SELECT column_name FROM information_schema.columns WHERE table_name = '{view_name}'"
            ).fetchall()
            columns = [row[0] for row in schema_result]

        for col in columns:
            try:
                stats = con.con.execute(
                    f"""SELECT COUNT(*) total,
                               COUNT("{col}") non_null,
                               COUNT(DISTINCT "{col}") distinct_count,
                               MIN(CAST("{col}" AS VARCHAR)) min_val,
                               MAX(CAST("{col}" AS VARCHAR)) max_val
                        FROM {view_name}"""
                ).fetchone()
                detail_dict = {
                    "total": stats[0],
                    "non_null": stats[1],
                    "distinct_count": stats[2],
                    "min_val": stats[3],
                    "max_val": stats[4],
                }
                result = QualityResult(
                    contract_id=str(_uuid_mod.uuid4()),
                    contract_type="column_profile",
                    passed=True,
                    severity="warn",
                    detail=_json.dumps(detail_dict),
                )
                if on_quality_result is not None:
                    on_quality_result(idx, result)
            except Exception:
                pass
    finally:
        try:
            con.con.execute(f"DROP VIEW IF EXISTS {view_name}")
        except Exception:
            pass

    return table


def _apply_filter(
    table: ibis.Table,
    step: FilterStep,
    engine: BaseEngine | None = None,
) -> ibis.Table:
    """Apply a raw SQL WHERE-clause fragment.

    When *engine* is supplied the call routes through
    ``engine.apply_filter_sql`` so each backend can handle portability
    (e.g. Trino raises ``TrinoRawSqlNotSupported``).  Without an engine
    the legacy ``table._find_backend()`` path is used — no behaviour change
    for existing DuckDB-only callers.
    """
    if engine is not None:
        return engine.apply_filter_sql(table, step.expr)
    con = table._find_backend()
    view_name = "_dte_filter_input"
    con.create_view(view_name, table, overwrite=True)
    return con.sql(f"SELECT * FROM {view_name} WHERE {step.expr}")


def _apply_rename(table: ibis.Table, step: RenameStep) -> ibis.Table:
    unknown = [old for old in step.mappings if old not in table.columns]
    if unknown:
        raise CompilerError(
            f"rename: unknown source field(s) {unknown!r}; "
            f"available columns: {sorted(table.columns)}"
        )
    return table.rename({v: k for k, v in step.mappings.items()})


def _apply_retype(table: ibis.Table, step: RetypeStep) -> ibis.Table:
    # to_type is Literal-validated on RetypeStep, so unknown values never reach
    # here. Field name isn't — check it and raise a typed error.
    if step.field not in table.columns:
        raise CompilerError(
            f"retype: unknown field {step.field!r}; available columns: {sorted(table.columns)}"
        )
    ibis_type = _TYPE_MAP[step.to_type]
    return table.cast({step.field: ibis_type})


def _apply_lookup(
    table: ibis.Table,
    step: LookupMapStep,
    lookup_tables: dict[str, LookupTable],
) -> ibis.Table:
    if step.lookup_id not in lookup_tables:
        raise CompilerError(f"map/lookup: unknown lookup_id {step.lookup_id!r}")
    lt = lookup_tables[step.lookup_id]
    col = _resolve_field(table, step.field)
    cases = [(col == k, ibis.literal(v)) for k, v in lt.mappings.items()]
    default = ibis.literal(lt.default) if lt.default is not None else None
    expr = ibis.cases(*cases, else_=default)
    # Struct paths can't be mutated in place; the output column takes the
    # leaf name at the top level of the resulting table (unless output_field
    # is explicitly set).
    out_name = step.output_field or (
        step.field.split(".")[-1] if "." in step.field else step.field
    )
    return table.mutate(**{out_name: expr})


def _apply_expression(
    table: ibis.Table,
    step: ExpressionMapStep,
    engine: BaseEngine | None = None,
) -> ibis.Table:
    """Add a computed column via raw SQL expression.

    When *engine* is supplied the call routes through
    ``engine.apply_expression_sql`` so each backend can handle portability.
    Without an engine the legacy ``table._find_backend()`` path is used.
    """
    if engine is not None:
        return engine.apply_expression_sql(table, step.output_field, step.expr)
    con = table._find_backend()
    view_name = "_dte_expr_input"
    con.create_view(view_name, table, overwrite=True)
    return con.sql(
        f'SELECT *, ({step.expr}) AS "{step.output_field}" FROM {view_name}'
    )


def _case_value(col: ibis.Column, raw: str):
    """Turn a builder-supplied string into a literal comparable to *col*.

    Bare numbers and true/false are taken at face value; everything else is a
    string, cast to the column's own type so a date column compared against
    "2008-01-01" emits CAST('2008-01-01' AS DATE) on any backend instead of a
    string comparison that silently sorts lexically.
    """
    v = raw.strip()
    if re.fullmatch(r"-?\d+", v):
        return ibis.literal(int(v))
    if re.fullmatch(r"-?\d+\.\d+", v):
        return ibis.literal(float(v))
    if v.lower() in ("true", "false"):
        return ibis.literal(v.lower() == "true")
    lit = ibis.literal(v)
    return lit if col.type().is_string() else lit.cast(col.type())


def _condition_expr(table: ibis.Table, cond: CaseCondition):
    col = _resolve_field(table, cond.field)
    op = cond.op
    if op == "IS NULL":
        return col.isnull()
    if op == "IS NOT NULL":
        return col.notnull()
    if op == "IN":
        items = [p.strip() for p in cond.value.split(",") if p.strip()]
        if not items:
            raise CompilerError(f"case: IN condition on {cond.field!r} has no values")
        return col.isin([_case_value(col, i) for i in items])
    if op == "BETWEEN":
        items = [p.strip() for p in cond.value.split(",") if p.strip()]
        if len(items) != 2:
            raise CompilerError(
                f"case: BETWEEN condition on {cond.field!r} needs exactly two values"
            )
        return col.between(_case_value(col, items[0]), _case_value(col, items[1]))
    if op == "LIKE":
        return col.like(cond.value)
    value = _case_value(col, cond.value)
    return {
        "=": lambda: col == value,
        "!=": lambda: col != value,
        ">": lambda: col > value,
        "<": lambda: col < value,
        ">=": lambda: col >= value,
        "<=": lambda: col <= value,
    }[op]()


def _case_predicate(table: ibis.Table, conditions: list[CaseCondition]):
    """Combine condition rows with SQL's precedence: AND binds tighter than OR.

    Folding strictly left-to-right would make `a OR b AND c` mean `(a OR b)
    AND c` — the opposite of what the same rows mean in the Filter tab, which
    hands its string to SQL.
    """
    groups: list[list] = [[]]
    for i, cond in enumerate(conditions):
        if i > 0 and cond.join == "OR":
            groups.append([])
        groups[-1].append(_condition_expr(table, cond))
    ands = [functools.reduce(operator.and_, g) for g in groups]
    return functools.reduce(operator.or_, ands)


def _apply_case(table: ibis.Table, step: CaseStep) -> ibis.Table:
    branches = [
        (_case_predicate(table, b.when), ibis.literal(b.then) if b.then is not None else ibis.null())
        for b in step.branches
    ]
    else_ = ibis.literal(step.otherwise) if step.otherwise is not None else None
    return table.mutate(**{step.output_field: ibis.cases(*branches, else_=else_)})


def _apply_sort(table: ibis.Table, step: SortStep) -> ibis.Table:
    ascending = step.ascending
    if isinstance(ascending, bool):
        ascending = [ascending] * len(step.by)

    order_exprs = []
    for col, asc in zip(step.by, ascending, strict=False):
        expr = _resolve_field(table, col)
        order_exprs.append(ibis.asc(expr) if asc else ibis.desc(expr))

    return table.order_by(order_exprs)


def _apply_aggregate(table: ibis.Table, step: AggregateStep) -> ibis.Table:
    agg_exprs = []
    for agg in step.aggregations:
        col = _resolve_field(table, agg.field)
        if agg.func == "sum":
            expr = col.sum()
        elif agg.func == "count":
            expr = col.count()
        elif agg.func == "avg":
            expr = col.mean()
        elif agg.func == "min":
            expr = col.min()
        elif agg.func == "max":
            expr = col.max()
        elif agg.func == "count_distinct":
            expr = col.nunique()
        agg_exprs.append(expr.name(agg.alias))

    group_by_exprs = [_resolve_group_by(table, g) for g in step.group_by]
    return table.group_by(group_by_exprs).aggregate(agg_exprs)


def _resolve_group_by(table: ibis.Table, entry: str | DatePartGroupBy) -> ibis.Expr:
    if isinstance(entry, str):
        return _resolve_field(table, entry).name(entry)
    # DatePartGroupBy — extract a temporal component.
    col = _resolve_field(table, entry.field)
    col_type = col.type()
    if not (col_type.is_timestamp() or col_type.is_date()):
        raise CompilerError(
            f"aggregate group_by part={entry.part!r} requires a date/timestamp field; "
            f"{entry.field!r} is {col_type}"
        )
    part = entry.part
    if part == "year":
        expr = col.year()
    elif part == "quarter":
        expr = col.quarter()
    elif part == "month":
        expr = col.month()
    elif part == "week":
        expr = col.week_of_year()
    elif part == "day":
        expr = col.day()
    elif part == "date":
        # Truncate timestamp to date; dates stay as-is.
        expr = col.date() if col_type.is_timestamp() else col
    elif part == "dow":
        expr = col.day_of_week.index()
    elif part == "hour":
        if not col_type.is_timestamp():
            raise CompilerError(
                f"aggregate group_by part='hour' requires a timestamp; "
                f"{entry.field!r} is {col_type}"
            )
        expr = col.hour()
    else:  # pragma: no cover — Literal guard
        raise CompilerError(f"unknown date part {part!r}")
    alias = entry.alias or f"{entry.field.split('.')[-1]}_{part}"
    return expr.name(alias)


def _apply_output_fields(
    table: ibis.Table,
    fields: list[OutputField],
    keep_system: bool = False,
) -> ibis.Table:
    selections = []
    named: set[str] = set()
    for f in fields:
        col = _resolve_field(table, f.field)
        if f.alias:
            col = col.name(f.alias)
        elif "." in f.field:
            # struct traversal — give the projected column a stable name
            # from the leaf segment rather than a compiler-generated one.
            col = col.name(f.field.split(".")[-1])
        named.add(f.field)
        selections.append(col)

    if keep_system:
        # Appended, not prepended: these are plumbing, and leading with a wall
        # of hashes would push the user's actual data off the side of every
        # table in the UI.
        selections.extend(
            table[c] for c in SYSTEM_COLUMNS if c in table.columns and c not in named
        )

    return table.select(selections)
