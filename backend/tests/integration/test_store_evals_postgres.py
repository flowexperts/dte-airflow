"""Postgres-backed eval store tests (plan 051, phase 1).

`tests/unit/test_eval_stores.py` runs the same contract against the fakes.
These exist because three of the guarantees are enforced by the *database*,
not by Python: the `(eval_set_id, doc_key)` UNIQUE constraint, the
`ON DELETE CASCADE` from set to examples, and the in-SQL `labels_version`
increment.
"""
import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("DTE_DATABASE_URL"), reason="requires DTE_DATABASE_URL"),
]

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from dte.models.eval import EvalExampleBase, EvalSetBase
from dte.store.postgres import (
    PostgresEvalExampleStore,
    PostgresEvalSetStore,
    PostgresRunStore,
)

KEY_A = "a" * 64
KEY_B = "b" * 64


@pytest.fixture
async def session_factory():
    engine = create_async_engine(os.environ["DTE_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def _set(id: str) -> EvalSetBase:
    return EvalSetBase(
        id=id,
        name=f"set {id}",
        source_id="docs",
        field_specs=[
            {"name": "total", "type": "numeric", "comparator": {"rel_tol": 0.01}}
        ],
    )


def _example(set_id: str, doc_key: str, **kw) -> EvalExampleBase:
    return EvalExampleBase(
        id=kw.pop("id", ""),
        eval_set_id=set_id,
        doc_key=doc_key,
        labels=kw.pop("labels", {"total": "1240.50"}),
        label_source=kw.pop("label_source", "human"),
        **kw,
    )


async def test_eval_set_roundtrip(session_factory):
    store = PostgresEvalSetStore(session_factory)
    await store.save(_set("pg-es1"))
    got = await store.get("pg-es1")
    assert got is not None
    assert got.field_specs[0]["comparator"] == {"rel_tol": 0.01}
    assert got.labels_version == 1
    assert await store.delete("pg-es1") is True


async def test_save_does_not_reset_labels_version(session_factory):
    """Renaming a set must not invalidate every score recorded against it."""
    store = PostgresEvalSetStore(session_factory)
    await store.save(_set("pg-es2"))
    assert await store.bump_labels_version("pg-es2") == 2

    renamed = _set("pg-es2")
    renamed.name = "renamed"
    await store.save(renamed)

    got = await store.get("pg-es2")
    assert got.name == "renamed"
    assert got.labels_version == 2
    await store.delete("pg-es2")


async def test_example_upsert_hits_the_unique_constraint(session_factory):
    """The UNIQUE (eval_set_id, doc_key) is what makes relabeling a replace.
    A fresh `id` on the second write must not create a second row."""
    sets = PostgresEvalSetStore(session_factory)
    store = PostgresEvalExampleStore(session_factory)
    await sets.save(_set("pg-es3"))
    try:
        await store.save(_example("pg-es3", KEY_A, labels={"total": "1"}))
        await store.save(
            _example("pg-es3", KEY_A, labels={"total": "2"}, label_source="judge")
        )
        rows = await store.list_for_set("pg-es3")
        assert len(rows) == 1
        assert rows[0].labels == {"total": "2"}
        assert rows[0].label_source == "judge"
    finally:
        await sets.delete("pg-es3")


async def test_deleting_a_set_cascades_to_its_examples(session_factory):
    sets = PostgresEvalSetStore(session_factory)
    store = PostgresEvalExampleStore(session_factory)
    await sets.save(_set("pg-es4"))
    await store.save(_example("pg-es4", KEY_A))
    await store.save(_example("pg-es4", KEY_B, split="holdout"))
    assert await store.count_for_set("pg-es4") == 2

    await sets.delete("pg-es4")
    assert await store.list_for_set("pg-es4") == []


async def test_split_filter_and_label_source_counts(session_factory):
    sets = PostgresEvalSetStore(session_factory)
    store = PostgresEvalExampleStore(session_factory)
    await sets.save(_set("pg-es5"))
    try:
        await store.save(_example("pg-es5", KEY_A, split="train", label_source="human"))
        await store.save(_example("pg-es5", KEY_B, split="holdout", label_source="judge"))
        assert await store.count_for_set("pg-es5", split="holdout") == 1
        assert [e.doc_key for e in await store.list_for_set("pg-es5", split="train")] == [KEY_A]
        assert await store.count_by_label_source("pg-es5") == {"human": 1, "judge": 1}
    finally:
        await sets.delete("pg-es5")


async def test_run_eval_columns_survive_the_round_trip(session_factory):
    """`run_results` is raw SQL with no SQLModel — a column missing from the
    select list vanishes silently, so read it back from both read paths."""
    from sqlalchemy import text

    async def dag_runs(dag_ids=None, run_id=None):
        return [{"run_id": "pg-evr", "dag_id": "dte__pg-evp", "state": "success", "queued_at": None,
                 "start_date": None, "end_date": None, "run_type": "manual", "conf": {}}]

    r_store = PostgresRunStore(session_factory, dag_runs=dag_runs)
    async with session_factory() as s:
        await s.execute(text(
            "INSERT INTO run_results (run_id, dag_id, pipeline_id, status, eval_set_id, labels_version, "
            "config_digest, sweep_id, scores) VALUES ('pg-evr', 'dte__pg-evp', 'pg-evp', 'completed', "
            "'pg-es-run', 3, :d, 'sw1', CAST(:s AS jsonb))"), {"d": "d" * 64, "s": '{"macro_f1": 0.91, "n": 42}'})
        await s.commit()
    try:
        got = await r_store.get("pg-evr")
        assert got["eval_set_id"] == "pg-es-run"
        assert got["labels_version"] == 3
        assert got["config_digest"] == "d" * 64
        assert got["sweep_id"] == "sw1"
        assert got["scores"] == {"macro_f1": 0.91, "n": 42}

        by_pipeline = await r_store.list_for_pipeline("pg-evp")
        assert by_pipeline[0]["scores"] == {"macro_f1": 0.91, "n": 42}

        by_set = await r_store.list_for_eval_set("pg-es-run")
        assert [r["id"] for r in by_set] == ["pg-evr"]
    finally:
        await r_store.delete_for_pipeline("pg-evp")
