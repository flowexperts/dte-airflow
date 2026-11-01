"""Sync pipeline runner: loader -> compiler -> engine -> contracts.

No stores, no HTTP, no Airflow imports. Callers resolve sources/destination
(with credentials) first and map `RunResult.status` to their own outcome.
"""
from __future__ import annotations

import itertools
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import ibis

from dte.compiler.ibis_compiler import compile_pipeline
from dte.compiler.interpolate import interpolate_pipeline, resolve_context
from dte.config import get_settings
from dte.engine.backend_registry import BackendRegistry
from dte.engine.registry import get_engine
from dte.models.pipeline import resolve_pipeline_engine
from dte.sources.loader import load_source

_STAGE_SEQ = itertools.count()

# on_event(step_idx, op, status, message)
EventCb = Callable[[int, str, str, "str | None"], None]


@dataclass
class RunResult:
    status: str  # completed | completed_with_warnings | failed_quality
    rows_written: int = 0
    location: str | None = None
    quality: list[dict] = field(default_factory=list)
    scores: dict | None = None
    sql_query: dict | None = None
    labels_version: int | None = None
    config_digest: str | None = None


def _quality_status(results) -> str:
    if any(not r.passed and r.severity == "fail" for r in results):
        return "failed_quality"
    if any(not r.passed and r.severity == "warn" for r in results):
        return "completed_with_warnings"
    return "completed"


def run_pipeline(
    pipeline,
    sources: list[tuple[Any, Any, Any, dict]],
    destination: tuple[Any, dict] | None = None,
    params: dict | None = None,
    on_event: EventCb | None = None,
    *,
    lookups: dict | None = None,
    run_id: str = "",
    eval_set=None,
    eval_examples: list | None = None,
) -> RunResult:
    """`sources` = [(SourceTableRef, Source, Connection, creds)],
    `destination` = (Destination, creds) for transform pipelines only."""
    settings = get_settings()
    lookups = lookups or {}
    pipeline = interpolate_pipeline(pipeline, params or resolve_context(pipeline))
    ptype = getattr(pipeline, "pipeline_type", "transform") or "transform"

    engine_name = resolve_pipeline_engine(
        getattr(pipeline, "engine", None) or "auto",
        [conn.connection_type for _, _, conn, _ in sources],
    )
    engine = get_engine(engine_name)
    registry = BackendRegistry(duckdb_con=engine.con)
    tables = {
        ref.alias: load_source(s, registry, conn, creds, table=ref.table)
        for ref, s, conn, creds in sources
    }

    step_sqls: dict[int, str] = {}
    kw: dict[str, Any] = dict(
        lookup_tables=lookups,
        engine=engine,
        on_step=on_event or (lambda *a: None),
        on_step_sql=lambda i, sql: step_sqls.__setitem__(i, sql),
    )
    steps_sql = lambda: {str(k): v for k, v in step_sqls.items()}  # noqa: E731

    if ptype == "quality":
        results: list = []
        compile_pipeline(pipeline, tables, on_quality_result=lambda _i, r: results.append(r), **kw)
        return RunResult(
            status=_quality_status(results),
            quality=[r.model_dump() for r in results],
            sql_query={"step_sqls": steps_sql()} if step_sqls else None,
        )

    if ptype == "eval":
        return _run_eval(pipeline, tables, kw, engine, eval_set, eval_examples or [])

    dest, dest_creds = destination
    compiled = compile_pipeline(pipeline, tables, output=dest.config, **kw)
    final_sql = None
    try:
        final_sql = str(ibis.to_sql(compiled.limit(settings.run_max_rows), dialect=getattr(engine, "dialect", "duckdb")))
    except Exception:
        pass
    compiled = compiled.limit(settings.run_max_rows)

    contracts = _contracts(pipeline)
    pre = [c for c in contracts if c.phase == "pre"]
    post = [c for c in contracts if c.phase == "post"]
    quality: list = []
    if pre:
        # Check before publishing (plan 086): a rejected result must never
        # overwrite the destination.
        from dte.quality.evaluator import evaluate_contracts_on_table
        compiled = _on_engine(compiled, engine.con)
        quality = evaluate_contracts_on_table(pre, compiled, engine.con)
        if _quality_status(quality) == "failed_quality":
            return RunResult(
                status="failed_quality",
                quality=[r.model_dump() for r in quality],
                sql_query={"step_sqls": steps_sql(), "final_sql": final_sql} if (step_sqls or final_sql) else None,
            )
    result = engine.execute(compiled, dest.config, credentials=dest_creds, run_id=run_id)

    if post:
        from dte.quality.evaluator import evaluate_contracts
        quality += evaluate_contracts(post, dest.config, engine.con)
    return RunResult(
        status=_quality_status(quality),
        rows_written=result["rows_written"],
        location=result["location"],
        quality=[r.model_dump() for r in quality],
        sql_query={"step_sqls": steps_sql(), "final_sql": final_sql} if (step_sqls or final_sql) else None,
    )


def _contracts(pipeline) -> list:
    """Typed contracts. The `Pipeline` table class skips validators, so a
    pipeline rebuilt from a revision carries them as plain dicts."""
    raw = getattr(pipeline, "quality_contracts", None) or []
    if not raw:
        return []
    from pydantic import TypeAdapter

    from dte.models.quality import Contract
    return TypeAdapter(list[Contract]).validate_python(
        [c if isinstance(c, dict) else c.model_dump() for c in raw])


def _on_engine(table, con):
    """`table` queryable from DuckDB `con`. A natively-bound result (postgres
    source) is staged once through Arrow, so checks and the write share it
    instead of querying the source twice."""
    if table._find_backend() is con:
        return table
    name = f"_dte_checked_{next(_STAGE_SEQ)}"
    con.con.register(f"{name}_reader", table.to_pyarrow_batches())
    con.con.execute(f'CREATE TEMP TABLE "{name}" AS SELECT * FROM "{name}_reader"')  # nosec B608
    con.con.unregister(f"{name}_reader")
    return con.table(name)


def _run_eval(pipeline, tables, kw, engine, eval_set, examples) -> RunResult:
    from dte.evals.cost import throughput_stats
    from dte.evals.digest import config_digest
    from dte.evals.runner import join_and_score

    if eval_set is None:
        raise ValueError("eval pipeline run without an eval set — nothing to score against")
    # Pin before compiling: labels may be edited mid-run.
    labels_version = eval_set.labels_version
    compiled = compile_pipeline(pipeline, tables, **kw)
    df = compiled.limit(get_settings().run_max_rows).execute()
    rows = json.loads(df.to_json(orient="records", date_format="iso"))
    scores = join_and_score(rows, examples, eval_set.to_field_specs(), collect_failures=True)
    scores["throughput"] = throughput_stats(rows)
    return RunResult(
        status="completed",
        rows_written=scores.get("n", 0),
        scores=scores,
        labels_version=labels_version,
        config_digest=config_digest(pipeline),
    )
