import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from sqlalchemy import func as sa_func
from sqlalchemy import bindparam, text
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import select

from dte.models.dashboard import Dashboard, DashboardBase
from dte.models.eval import (
    EvalExample,
    EvalExampleBase,
    EvalSet,
    EvalSetBase,
)
from dte.models.pipeline import (
    Destination,
    DestinationBase,
    LookupTable,
    LookupTableBase,
    Pipeline,
    PipelineRevision,
    PipelineRevisionBase,
    Source,
    SourceBase,
)


# What `run_results` contributes to a run; the rest comes from the dag run.
_RESULT_COLUMNS = (
    "run_id", "dag_id", "pipeline_id", "revision_id", "status", "error", "rows_written", "location",
    "params", "quality_checks", "sql_query", "eval_set_id", "labels_version", "config_digest",
    "sweep_id", "scores",
)
_OPERATOR_STATUSES = ("completed", "completed_with_warnings", "failed_quality")
_NEVER = datetime.max.replace(tzinfo=timezone.utc)


def _merge(dag_run: dict, result: dict | None) -> dict:
    """One run: an Airflow dag run of `dte__<pipeline>` plus what the operator
    recorded for it. `conf` carries the trigger-time values, so queued runs
    already show their params / eval set / sweep."""
    rr = result if result and result.get("dag_id") == dag_run["dag_id"] else {}
    cf = dag_run.get("conf") or {}
    state = dag_run.get("state")
    if state in ("success", "failed"):
        status = rr.get("status") if rr.get("status") in _OPERATOR_STATUSES else (
            "completed" if state == "success" else "failed")
    else:
        status = "running" if state == "running" else "pending"
    return {
        "id": dag_run["run_id"],
        "pipeline_id": rr.get("pipeline_id") or dag_run["dag_id"][len("dte__"):],
        "revision_id": rr.get("revision_id") or cf.get("revision_id"),
        "status": status,
        "error": rr.get("error"), "rows_written": rr.get("rows_written"), "location": rr.get("location"),
        "started_at": dag_run.get("start_date") or dag_run.get("queued_at"),
        "finished_at": dag_run.get("end_date"),
        "params": rr["params"] if rr.get("params") is not None else cf.get("context"),
        "quality_checks": rr.get("quality_checks"), "sql_query": rr.get("sql_query"),
        "job_id": None, "last_heartbeat_at": None,
        "scheduled": dag_run.get("run_type") == "scheduled",
        "eval_set_id": rr.get("eval_set_id") or cf.get("eval_set_id"),
        "labels_version": rr.get("labels_version"), "config_digest": rr.get("config_digest"),
        "sweep_id": rr.get("sweep_id") or cf.get("sweep_id"),
        "scores": rr.get("scores"),
    }


def _quality_summary_dicts(results: list[dict]) -> dict:
    """Compute pass/fail/warn counts from a list of raw quality_checks dicts."""
    passed = sum(1 for r in results if r.get("passed"))
    warned = sum(1 for r in results if not r.get("passed") and r.get("severity") == "warn")
    failed = sum(1 for r in results if not r.get("passed") and r.get("severity") == "fail")
    return {"passed": passed, "failed": failed, "warned": warned}


def _run_row_to_dict(row) -> dict:
    """Shared post-processing for every `runs` read path: ISO-format the
    timestamps and collapse `quality_checks` into its summary."""
    d = dict(row)
    for ts in ("started_at", "finished_at", "last_heartbeat_at"):
        d[ts] = d[ts].isoformat() if d.get(ts) else None
    raw_quality = list(d.pop("quality_checks") or [])
    d["quality"] = _quality_summary_dicts(raw_quality)
    return d


@asynccontextmanager
async def _session(factory: async_sessionmaker[AsyncSession]):
    async with factory() as session:
        yield session


class PostgresPipelineStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def get(self, id: str) -> Pipeline | None:
        async with _session(self._factory) as s:
            return await s.get(Pipeline, id)

    async def save(self, pipeline: Pipeline) -> None:
        # Upsert via ON CONFLICT so a re-save touches `updated_at`
        # (session.merge would leave the column's `onupdate` unfired).
        values = pipeline.model_dump(exclude={"created_at", "updated_at"})
        stmt = pg_insert(Pipeline).values(**values)
        # The update set is derived from the values, not hand-listed. It used
        # to be a literal dict of seven columns, and `pipeline_type` and
        # `matrix` were not among them: both were written on INSERT and
        # silently dropped on UPDATE. Converting a pipeline's type returned
        # 200 and changed nothing — no error anywhere, and the fake store
        # (a plain dict) could not reproduce it.
        #
        # `id` is the conflict target. `tenant_id` is held out on purpose: a
        # re-save must never be able to move a row into another tenant.
        stmt = stmt.on_conflict_do_update(
            index_elements=[Pipeline.id],
            set_={
                k: stmt.excluded[k]
                for k in values
                if k not in ("id", "tenant_id")
            },
        )
        async with _session(self._factory) as s:
            await s.execute(stmt)
            await s.commit()

    async def list(self, limit: int = 50, offset: int = 0) -> list[Pipeline]:
        stmt = (
            select(Pipeline)
            .order_by(Pipeline.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with _session(self._factory) as s:
            return list((await s.execute(stmt)).scalars().all())

    async def delete(self, id: str) -> bool:
        async with _session(self._factory) as s:
            row = await s.get(Pipeline, id)
            if row is None:
                return False
            await s.delete(row)
            await s.commit()
            return True


class PostgresDashboardStore:
    """Dashboards. Layout only — see `DashboardStore` in store/base.py.

    The ON CONFLICT set is derived from the values rather than hand-listed,
    for the reason spelled out on `PostgresPipelineStore.save`: that store's
    literal column list silently dropped `pipeline_type` on every UPDATE.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def get(self, id: str) -> Dashboard | None:
        async with _session(self._factory) as s:
            return await s.get(Dashboard, id)

    async def save(self, dashboard: "DashboardBase | Dashboard") -> None:
        values = {
            "id": dashboard.id,
            "name": dashboard.name,
            "description": dashboard.description,
            # Tiles are Pydantic models on the Base class and plain dicts on
            # the table class. `mode="json"` normalises both, and is what
            # asyncpg needs for a JSONB bind.
            "tiles": [
                t if isinstance(t, dict) else t.model_dump(mode="json")
                for t in (dashboard.tiles or [])
            ],
        }
        stmt = pg_insert(Dashboard).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Dashboard.id],
            set_={k: stmt.excluded[k] for k in values if k != "id"},
        )
        async with _session(self._factory) as s:
            await s.execute(stmt)
            await s.commit()

    async def list(self, limit: int = 50, offset: int = 0) -> list[Dashboard]:
        stmt = (
            select(Dashboard)
            .order_by(Dashboard.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with _session(self._factory) as s:
            return list((await s.execute(stmt)).scalars().all())

    async def delete(self, id: str) -> bool:
        async with _session(self._factory) as s:
            row = await s.get(Dashboard, id)
            if row is None:
                return False
            await s.delete(row)
            await s.commit()
            return True


class PostgresRunStore:
    """Read-only view of a pipeline run: Airflow's dag run (status, timing)
    merged in Python with `dte.run_results` (scores, quality, sql). The dag
    runs come through Airflow's own session, so DTE's database can be any
    Postgres (plan 075). Runs are written by Airflow and by
    `DtePipelineOperator`, never here."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], dag_runs=None):
        if dag_runs is None:
            from dte.airflow.dag_runs import dag_runs
        self._factory = session_factory
        self._dag_runs = dag_runs

    async def _results(self, ids: list[str]) -> dict[str, dict]:
        if not ids:
            return {}
        q = text(f"SELECT {', '.join(_RESULT_COLUMNS)} FROM run_results WHERE run_id IN :ids").bindparams(
            bindparam("ids", expanding=True))
        async with _session(self._factory) as s:
            return {r["run_id"]: dict(r) for r in (await s.execute(q, {"ids": ids})).mappings()}

    async def _runs(self, keep=lambda r: True, dag_ids=None, run_id=None, desc=True,
                    limit: int | None = None, offset: int = 0) -> list[dict]:
        drs = await self._dag_runs(dag_ids=dag_ids, run_id=run_id)
        results = await self._results([d["run_id"] for d in drs])
        runs = [m for m in (_merge(d, results.get(d["run_id"])) for d in drs) if keep(m)]
        # Postgres' default NULL placement: first when DESC, last when ASC.
        runs.sort(key=lambda r: r["started_at"] or _NEVER, reverse=desc)
        runs = runs[offset:] if limit is None else runs[offset:offset + limit]
        return [_run_row_to_dict(r) for r in runs]

    async def get(self, id: str) -> dict | None:
        rows = await self._runs(run_id=id, limit=1)
        return rows[0] if rows else None

    async def list_for_pipeline(self, pipeline_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
        return await self._runs(dag_ids=[f"dte__{pipeline_id}"], limit=limit, offset=offset)

    # ponytail: the eval-set and sweep listings read every `dte__*` dag run and
    # filter here; push the filter into the DagRun query (conf JSON) if run
    # counts reach the tens of thousands.
    async def list_for_eval_set(self, eval_set_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
        """Every run scored against one eval set — the leaderboard's read path."""
        return await self._runs(lambda r: r["eval_set_id"] == eval_set_id, limit=limit, offset=offset)

    async def list_for_sweep(self, sweep_id: str, limit: int = 50) -> list[dict]:
        """Oldest-first so a comparison grid keeps the matrix's declared order."""
        return await self._runs(lambda r: r["sweep_id"] == sweep_id, desc=False, limit=limit)

    async def list_sweep_runs_for_root(self, root_pipeline_id: str, limit: int = 500) -> list[dict]:
        """A sweep's runs are filed under the *variants* it created
        (`root__digest`), never under the swept pipeline itself."""
        return await self._runs(
            lambda r: r["sweep_id"] is not None and (
                r["pipeline_id"] == root_pipeline_id or r["pipeline_id"].startswith(f"{root_pipeline_id}__")),
            limit=limit,
        )

    async def count_for_pipeline(self, pipeline_id: str) -> int:
        return len(await self._dag_runs(dag_ids=[f"dte__{pipeline_id}"]))

    async def delete_for_pipeline(self, pipeline_id: str) -> int:
        """Drops DTE's results only; Airflow keeps its own dag run history."""
        async with _session(self._factory) as s:
            result = await s.execute(
                text("DELETE FROM run_results WHERE pipeline_id = :pid"), {"pid": pipeline_id}
            )
            await s.commit()
            return result.rowcount

    async def get_quality(self, run_id: str) -> list:
        async with _session(self._factory) as s:
            result = await s.execute(
                text("SELECT quality_checks FROM run_results WHERE run_id = :id"), {"id": run_id}
            )
            row = result.mappings().fetchone()
            return list(row["quality_checks"] or []) if row else []


class PostgresPipelineRevisionStore:
    """Append-only history of pipeline configs. One row per accepted
    POST/PUT. Never upserts — the `id` is generated per-write."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def save(self, revision: "PipelineRevisionBase | PipelineRevision") -> None:
        stmt = pg_insert(PipelineRevision).values(
            id=revision.id,
            pipeline_id=revision.pipeline_id,
            config=revision.config,
            changed_by=revision.changed_by,
            summary=revision.summary,
        )
        async with _session(self._factory) as s:
            await s.execute(stmt)
            await s.commit()

    async def get(self, id: str) -> PipelineRevision | None:
        async with _session(self._factory) as s:
            return await s.get(PipelineRevision, id)

    async def list_for_pipeline(
        self, pipeline_id: str, limit: int = 100, offset: int = 0
    ) -> list[PipelineRevision]:
        stmt = (
            select(PipelineRevision)
            .where(PipelineRevision.pipeline_id == pipeline_id)
            .order_by(PipelineRevision.changed_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with _session(self._factory) as s:
            return list((await s.execute(stmt)).scalars().all())

    async def count_for_pipeline(self, pipeline_id: str) -> int:
        stmt = (
            select(sa_func.count())
            .select_from(PipelineRevision)
            .where(PipelineRevision.pipeline_id == pipeline_id)
        )
        async with _session(self._factory) as s:
            return int((await s.execute(stmt)).scalar_one())

    async def latest_for_pipeline(self, pipeline_id: str) -> PipelineRevision | None:
        stmt = (
            select(PipelineRevision)
            .where(PipelineRevision.pipeline_id == pipeline_id)
            .order_by(PipelineRevision.changed_at.desc())
            .limit(1)
        )
        async with _session(self._factory) as s:
            return (await s.execute(stmt)).scalars().first()


class PostgresRunEventStore:
    """Per-step events, kept as a JSON list on the run's `run_results` row."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def list_for_run(self, run_id: str) -> list[dict]:
        async with _session(self._factory) as s:
            result = await s.execute(
                text("SELECT events FROM run_results WHERE run_id = :id"), {"id": run_id}
            )
            row = result.mappings().fetchone()
            return list(row["events"] or []) if row else []


class PostgresSourceStore:
    """ORM-backed source store. Returns typed `Source` instances.

    `save` accepts a `Source` or `SourceBase` instance. The store uses
    pg_insert upsert so `updated_at` fires on re-save.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def get(self, id: str) -> Source | None:
        async with _session(self._factory) as s:
            return await s.get(Source, id)

    async def save(self, source: "SourceBase | Source") -> None:
        values = source.model_dump(exclude={"created_at", "updated_at"})
        # Guarantee name is set — historic callers may pass a Source ORM
        # instance whose validator never ran.
        if not values.get("name"):
            values["name"] = values["id"]
        stmt = pg_insert(Source).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Source.id],
            set_={
                "name": stmt.excluded.name,
                "source_type": stmt.excluded.source_type,
                "config": stmt.excluded.config,
                "table_name": stmt.excluded.table_name,
                "connection_id": stmt.excluded.connection_id,
                "format": stmt.excluded.format,
            },
        )
        async with _session(self._factory) as s:
            await s.execute(stmt)
            await s.commit()

    async def list(self, limit: int = 50, offset: int = 0) -> list[Source]:
        stmt = (
            select(Source)
            .order_by(Source.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with _session(self._factory) as s:
            return list((await s.execute(stmt)).scalars().all())

    async def delete(self, id: str) -> bool:
        async with _session(self._factory) as s:
            row = await s.get(Source, id)
            if row is None:
                return False
            await s.delete(row)
            await s.commit()
            return True


class PostgresDestinationStore:
    """ORM-backed destination store. Returns typed `Destination` instances.

    `save` accepts a `Destination` or `DestinationBase` instance. The store
    uses pg_insert upsert so `updated_at` fires on re-save. `config` is
    serialised to a plain dict for JSONB storage; on read, `narrow_config()`
    is called explicitly (table=True bypasses validators on hydration).

    `dest_type` is a denormalised column kept for backward compat; it is written
    explicitly at save time from `config.type` (drop in a follow-up migration).
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def get(self, id: str) -> Destination | None:
        async with _session(self._factory) as s:
            row = await s.get(Destination, id)
            if row is None:
                return None
            return row.narrow_config()

    async def save(self, destination: "DestinationBase | Destination") -> None:
        # Serialise config to a plain dict for JSONB storage. The `config`
        # field is the typed OutputTarget union in memory; model_dump gives
        # back a JSON-serialisable dict. `by_alias=True` so `schema_` → `schema`.
        cfg = destination.config
        if hasattr(cfg, "model_dump"):
            config_dict = cfg.model_dump(by_alias=True, exclude_none=True)
        else:
            config_dict = dict(cfg)  # already a plain dict
        dest_type = config_dict.get("type", "")

        stmt = pg_insert(Destination).values(
            id=destination.id,
            name=destination.name or destination.id,
            connection_id=destination.connection_id,
            config=config_dict,
            dest_type=dest_type,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[Destination.id],
            set_={
                "name": stmt.excluded.name,
                "connection_id": stmt.excluded.connection_id,
                "config": stmt.excluded.config,
                "dest_type": stmt.excluded.dest_type,
            },
        )
        async with _session(self._factory) as s:
            await s.execute(stmt)
            await s.commit()

    async def list(self, limit: int = 50, offset: int = 0) -> list[Destination]:
        stmt = (
            select(Destination)
            .order_by(Destination.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with _session(self._factory) as s:
            rows = list((await s.execute(stmt)).scalars().all())
        return [row.narrow_config() for row in rows]

    async def delete(self, id: str) -> bool:
        async with _session(self._factory) as s:
            row = await s.get(Destination, id)
            if row is None:
                return False
            await s.delete(row)
            await s.commit()
            return True


class PostgresLookupTableStore:
    """ORM-backed lookup table store. Returns typed `LookupTable` instances."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def get(self, id: str) -> LookupTable | None:
        async with _session(self._factory) as s:
            return await s.get(LookupTable, id)

    async def save(self, lookup: "LookupTableBase | LookupTable") -> None:
        values = {
            "id": lookup.id,
            "name": lookup.name or lookup.id,
            "mappings": lookup.mappings,
            "default": lookup.default,
        }
        stmt = pg_insert(LookupTable).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[LookupTable.id],
            set_={
                "name": stmt.excluded.name,
                "mappings": stmt.excluded.mappings,
                "default": stmt.excluded.default,
            },
        )
        async with _session(self._factory) as s:
            await s.execute(stmt)
            await s.commit()

    async def list(self, limit: int = 50, offset: int = 0) -> list[LookupTable]:
        stmt = (
            select(LookupTable)
            .order_by(LookupTable.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with _session(self._factory) as s:
            return list((await s.execute(stmt)).scalars().all())

    async def delete(self, id: str) -> bool:
        async with _session(self._factory) as s:
            row = await s.get(LookupTable, id)
            if row is None:
                return False
            await s.delete(row)
            await s.commit()
            return True


class PostgresEvalSetStore:
    """Labeled corpora (plan 051). Standard three-verb ORM template."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def get(self, id: str) -> EvalSet | None:
        async with _session(self._factory) as s:
            return await s.get(EvalSet, id)

    async def save(self, eval_set: "EvalSetBase | EvalSet") -> None:
        values = eval_set.model_dump(exclude={"created_at", "updated_at"})
        stmt = pg_insert(EvalSet).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[EvalSet.id],
            set_={
                "name": stmt.excluded.name,
                "source_id": stmt.excluded.source_id,
                "field_specs": stmt.excluded.field_specs,
                # `labels_version` is deliberately absent: it is owned by
                # `bump_labels_version`, so editing the name of a set can
                # never invalidate every score recorded against it.
            },
        )
        async with _session(self._factory) as s:
            await s.execute(stmt)
            await s.commit()

    async def list(self, limit: int = 50, offset: int = 0) -> list[EvalSet]:
        stmt = (
            select(EvalSet)
            .order_by(EvalSet.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with _session(self._factory) as s:
            return list((await s.execute(stmt)).scalars().all())

    async def delete(self, id: str) -> bool:
        async with _session(self._factory) as s:
            row = await s.get(EvalSet, id)
            if row is None:
                return False
            await s.delete(row)
            await s.commit()
            return True

    async def bump_labels_version(self, id: str) -> int:
        """Increment in SQL, not read-modify-write: two concurrent labelers
        must not both read 3 and both write 4, which would leave two different
        label states sharing one version and silently mis-pin every run."""
        async with _session(self._factory) as s:
            result = await s.execute(
                text(
                    "UPDATE eval_sets SET labels_version = labels_version + 1 "
                    "WHERE id = :id RETURNING labels_version"
                ),
                {"id": id},
            )
            row = result.fetchone()
            await s.commit()
            return int(row[0]) if row else 0


class PostgresEvalExampleStore:
    """One labeled document per row (plan 051).

    The upsert targets `(eval_set_id, doc_key)` rather than the primary key:
    the natural identity of a label is the document it labels, and relabeling
    must replace rather than accumulate.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def get(self, id: str) -> EvalExample | None:
        async with _session(self._factory) as s:
            return await s.get(EvalExample, id)

    async def get_by_doc_key(self, eval_set_id: str, doc_key: str) -> EvalExample | None:
        stmt = (
            select(EvalExample)
            .where(EvalExample.eval_set_id == eval_set_id)
            .where(EvalExample.doc_key == doc_key.lower())
        )
        async with _session(self._factory) as s:
            return (await s.execute(stmt)).scalars().first()

    async def save(self, example: "EvalExampleBase | EvalExample") -> None:
        values = example.model_dump(exclude={"created_at", "updated_at"})
        stmt = pg_insert(EvalExample).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[EvalExample.eval_set_id, EvalExample.doc_key],
            set_={
                "doc_ref": stmt.excluded.doc_ref,
                "labels": stmt.excluded.labels,
                "label_source": stmt.excluded.label_source,
                "split": stmt.excluded.split,
                "labels_version": stmt.excluded.labels_version,
            },
        )
        async with _session(self._factory) as s:
            await s.execute(stmt)
            await s.commit()

    async def list_for_set(
        self,
        eval_set_id: str,
        split: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[EvalExample]:
        stmt = select(EvalExample).where(EvalExample.eval_set_id == eval_set_id)
        if split is not None:
            stmt = stmt.where(EvalExample.split == split)
        stmt = stmt.order_by(EvalExample.created_at.asc()).limit(limit).offset(offset)
        async with _session(self._factory) as s:
            return list((await s.execute(stmt)).scalars().all())

    async def count_for_set(self, eval_set_id: str, split: str | None = None) -> int:
        stmt = (
            select(sa_func.count())
            .select_from(EvalExample)
            .where(EvalExample.eval_set_id == eval_set_id)
        )
        if split is not None:
            stmt = stmt.where(EvalExample.split == split)
        async with _session(self._factory) as s:
            return int((await s.execute(stmt)).scalar_one())

    async def count_by_label_source(self, eval_set_id: str) -> dict[str, int]:
        """Feeds the ">50% judge-labeled" warning. Grouped in SQL because the
        set can be thousands of rows and the leaderboard asks on every load."""
        stmt = (
            select(EvalExample.label_source, sa_func.count())
            .where(EvalExample.eval_set_id == eval_set_id)
            .group_by(EvalExample.label_source)
        )
        async with _session(self._factory) as s:
            return {src: int(n) for src, n in (await s.execute(stmt)).all()}

    async def delete(self, id: str) -> bool:
        async with _session(self._factory) as s:
            row = await s.get(EvalExample, id)
            if row is None:
                return False
            await s.delete(row)
            await s.commit()
            return True
