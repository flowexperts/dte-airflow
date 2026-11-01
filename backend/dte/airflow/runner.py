"""Sync pipeline runner: loader -> compiler -> engine -> contracts.

No stores, no HTTP, no Airflow imports. Callers resolve sources/destination
(with credentials) first and map `RunResult.status` to their own outcome.
"""
from __future__ import annotations

import itertools
import json
import logging
import time
from collections.abc import Callable
from contextlib import contextmanager
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
from dte.sources.metered import QueryCapExceeded, cap_message

_STAGE_SEQ = itertools.count()

# on_event(step_idx, op, status, message). A run phase (source load, write,
# contracts) arrives with step_idx=None and its title as `op`.
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


@contextmanager
def _phase(log, emit, title: str, group: bool = True):
    """A timed phase, folded into an Airflow collapsible log group and reported
    to `emit` as a step_idx=None event. Groups don't nest, so a phase that
    contains per-step groups passes group=False."""
    log.info("::group::%s" if group else "== %s", title)
    emit(None, title, "started")
    t0 = time.monotonic()
    try:
        yield
    except Exception as e:
        # A connection's cap (plan 093) reads as a driver traceback otherwise.
        if (msg := cap_message(e)) is not None:
            emit(None, title, "failed", msg)
            raise QueryCapExceeded(msg) from e
        emit(None, title, "failed", f"{type(e).__name__}: {e}")
        raise
    else:
        emit(None, title, "completed")
    finally:
        if group:
            log.info("::endgroup::")
        log.info("%s took %.2fs", title, time.monotonic() - t0)


def _log_quality(log, results) -> None:
    for r in results:
        verdict = "PASS" if r.passed else r.severity.upper()
        level = logging.INFO if r.passed else (logging.ERROR if r.severity == "fail" else logging.WARNING)
        log.log(level, "check %s [%s]: %s %s", r.label or r.contract_id, r.severity, verdict, r.detail or "")


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
    log: logging.Logger | None = None,
) -> RunResult:
    """`sources` = [(SourceTableRef, Source, Connection, creds)],
    `destination` = (Destination, creds) for transform pipelines only."""
    settings = get_settings()
    log = log or logging.getLogger("dte.runner")
    lookups = lookups or {}
    pipeline = interpolate_pipeline(pipeline, params or resolve_context(pipeline))
    ptype = getattr(pipeline, "pipeline_type", "transform") or "transform"

    def emit(idx, op, status, msg=None):
        if on_event:
            on_event(idx, op, status, msg)

    def phase(title, group=True):
        return _phase(log, emit, title, group)

    engine_name = resolve_pipeline_engine(
        getattr(pipeline, "engine", None) or "auto",
        [conn.connection_type for _, _, conn, _ in sources],
    )
    engine = get_engine(engine_name)
    # Keys only: resolved params may carry secrets.
    log.info("%s pipeline on %s: %d source(s), %d step(s), params=%s", ptype, engine_name,
             len(sources), len(pipeline.steps or []), sorted((params or {}).keys()))
    registry = BackendRegistry(duckdb_con=engine.con)
    tables = {}
    for ref, s, conn, creds in sources:
        with phase(f"load source {ref.alias}"):
            tables[ref.alias] = t = load_source(s, registry, conn, creds, table=ref.table)
            log.info("source %s: %s table=%s, %d cols %s", ref.alias, conn.connection_type,
                     ref.table or getattr(s, "table", None), len(t.columns), list(t.columns))

    step_sqls: dict[int, str] = {}
    ops = {i: st.get("op") for i, st in enumerate(pipeline.steps or [])}
    # One log group per step. The compiler reports a step's schema and SQL
    # after "completed", so a group stays open until the next step starts.
    step_t0: dict[int, float] = {}
    open_group = []

    def close_group():
        if open_group:
            log.info("::endgroup::")
            open_group.clear()

    def _on_step(idx, op, status, msg=None):
        if status == "started":
            close_group()
            log.info("::group::step #%d %s", idx, op)
            open_group.append(idx)
            step_t0[idx] = time.monotonic()
        else:
            if status == "failed":
                log.error("step #%d %s failed: %s", idx, op, msg)
            log.info("step #%d %s took %.2fs", idx, op, time.monotonic() - step_t0.get(idx, time.monotonic()))
        emit(idx, op, status, msg)

    def _on_sql(idx, sql):
        step_sqls[idx] = sql
        log.info("SQL:\n%s", sql)

    def compile_steps(**extra):
        try:
            return compile_pipeline(pipeline, tables, **kw, **extra)
        finally:
            close_group()

    kw: dict[str, Any] = dict(
        lookup_tables=lookups,
        engine=engine,
        on_step=_on_step,
        on_step_sql=_on_sql,
        on_step_schema=lambda i, cols: log.info("step #%d %s -> %d cols %s", i, ops.get(i), len(cols), cols),
        on_enrichment_stats=lambda i, st: log.info("step #%d %s enrichment: %s", i, ops.get(i), st),
    )
    steps_sql = lambda: {str(k): v for k, v in step_sqls.items()}  # noqa: E731

    if ptype == "quality":
        results: list = []
        # Checks execute while compiling, so this phase is real work here.
        with phase("compile + run checks", group=False):
            compile_steps(on_quality_result=lambda _i, r: results.append(r))
        _log_quality(log, results)
        return RunResult(
            status=_quality_status(results),
            quality=[r.model_dump() for r in results],
            sql_query={"step_sqls": steps_sql()} if step_sqls else None,
        )

    if ptype == "eval":
        return _run_eval(pipeline, compile_steps, phase, log, eval_set, eval_examples or [])

    dest, dest_creds = destination
    # Lazy: most steps only build the query (eager ones like extract/structure
    # run here), so the real cost of the rest lands in "execute + write".
    with phase("compile steps", group=False):
        compiled = compile_steps(output=dest.config)
    final_sql = None
    try:
        final_sql = str(ibis.to_sql(compiled.limit(settings.run_max_rows), dialect=getattr(engine, "dialect", "duckdb")))
    except Exception:
        pass
    compiled = compiled.limit(settings.run_max_rows)
    if final_sql:
        log.info("::group::final SQL")
        log.info("%s", final_sql)
        log.info("::endgroup::")

    contracts = _contracts(pipeline)
    pre = [c for c in contracts if c.phase == "pre"]
    post = [c for c in contracts if c.phase == "post"]
    quality: list = []
    if pre:
        # Check before publishing (plan 086): a rejected result must never
        # overwrite the destination.
        from dte.quality.evaluator import evaluate_contracts_on_table
        with phase(f"quality contracts before write ({len(pre)})"):
            compiled = _on_engine(compiled, engine.con)
            quality = evaluate_contracts_on_table(pre, compiled, engine.con)
        _log_quality(log, quality)
        if _quality_status(quality) == "failed_quality":
            return RunResult(
                status="failed_quality",
                quality=[r.model_dump() for r in quality],
                sql_query={"step_sqls": steps_sql(), "final_sql": final_sql} if (step_sqls or final_sql) else None,
            )
    with phase(f"execute + write to {getattr(dest.config, 'type', dest.dest_type)}", group=False):
        result = engine.execute(compiled, dest.config, credentials=dest_creds, run_id=run_id)
        log.info("rows written: %s -> %s", result["rows_written"], result["location"])

    if post:
        from dte.quality.evaluator import evaluate_contracts
        with phase(f"quality contracts after write ({len(post)})"):
            post_results = evaluate_contracts(post, dest.config, engine.con)
        _log_quality(log, post_results)
        quality += post_results
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


def _run_eval(pipeline, compile_steps, phase, log, eval_set, examples) -> RunResult:
    from dte.evals.cost import throughput_stats
    from dte.evals.digest import config_digest
    from dte.evals.runner import join_and_score

    if eval_set is None:
        raise ValueError("eval pipeline run without an eval set — nothing to score against")
    # Pin before compiling: labels may be edited mid-run.
    labels_version = eval_set.labels_version
    with phase("compile steps", group=False):
        compiled = compile_steps()
    with phase("execute"):
        df = compiled.limit(get_settings().run_max_rows).execute()
        rows = json.loads(df.to_json(orient="records", date_format="iso"))
        log.info("rows produced: %d", len(rows))
    with phase(f"score against {len(examples)} labelled example(s)"):
        scores = join_and_score(rows, examples, eval_set.to_field_specs(), collect_failures=True)
        scores["throughput"] = throughput_stats(rows)
    log.info("scores: %s", {k: v for k, v in scores.items() if isinstance(v, (int, float))})
    return RunResult(
        status="completed",
        rows_written=scores.get("n", 0),
        scores=scores,
        labels_version=labels_version,
        config_digest=config_digest(pipeline),
    )
