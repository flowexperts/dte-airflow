"""Store-contract tests for the eval harness (plan 051, phase 1).

Run against the fakes. `tests/integration/test_store_postgres.py` runs the
same expectations against real Postgres — the fakes exist so the contract is
enforced in the default suite too.
"""
from __future__ import annotations

import pytest

from dte.models.eval import EvalExampleBase, EvalSetBase
from tests.fakes import FakeEvalExampleStore, FakeEvalSetStore, FakeRunStore

KEY_A = "a" * 64
KEY_B = "b" * 64


def _set(id: str = "es1", **kw) -> EvalSetBase:
    return EvalSetBase(
        id=id,
        name=kw.pop("name", "Invoices"),
        source_id=kw.pop("source_id", "docs"),
        field_specs=kw.pop("field_specs", [{"name": "total", "type": "numeric"}]),
        **kw,
    )


def _example(doc_key: str, **kw) -> EvalExampleBase:
    return EvalExampleBase(
        id=kw.pop("id", ""),
        eval_set_id=kw.pop("eval_set_id", "es1"),
        doc_key=doc_key,
        labels=kw.pop("labels", {"total": "1240.50"}),
        label_source=kw.pop("label_source", "human"),
        **kw,
    )


@pytest.mark.asyncio
async def test_eval_set_roundtrip_and_delete():
    store = FakeEvalSetStore()
    await store.save(_set())
    got = await store.get("es1")
    assert got is not None and got.name == "Invoices"
    assert [s["name"] for s in got.field_specs] == ["total"]

    assert await store.delete("es1") is True
    assert await store.get("es1") is None
    assert await store.delete("es1") is False


@pytest.mark.asyncio
async def test_bump_labels_version_is_monotonic():
    """Every label write bumps the version so runs can pin what they scored."""
    store = FakeEvalSetStore()
    await store.save(_set())
    assert await store.bump_labels_version("es1") == 2
    assert await store.bump_labels_version("es1") == 3
    got = await store.get("es1")
    assert got.labels_version == 3


@pytest.mark.asyncio
async def test_example_upsert_is_keyed_by_doc_key_not_id():
    """Relabeling the same document must replace the label, not accumulate a
    second contradictory one."""
    store = FakeEvalExampleStore()
    await store.save(_example(KEY_A, labels={"total": "1"}))
    await store.save(_example(KEY_A, labels={"total": "2"}, label_source="judge"))

    rows = await store.list_for_set("es1")
    assert len(rows) == 1
    assert rows[0].labels == {"total": "2"}
    assert rows[0].label_source == "judge"


@pytest.mark.asyncio
async def test_get_by_doc_key_scoped_to_the_set():
    store = FakeEvalExampleStore()
    await store.save(_example(KEY_A, eval_set_id="es1"))
    await store.save(_example(KEY_A, eval_set_id="es2"))

    a = await store.get_by_doc_key("es1", KEY_A)
    b = await store.get_by_doc_key("es2", KEY_A)
    assert a is not None and b is not None and a.id != b.id
    assert await store.get_by_doc_key("es3", KEY_A) is None


@pytest.mark.asyncio
async def test_list_for_set_filters_by_split():
    store = FakeEvalExampleStore()
    await store.save(_example(KEY_A, split="train"))
    await store.save(_example(KEY_B, split="holdout"))

    assert len(await store.list_for_set("es1")) == 2
    holdout = await store.list_for_set("es1", split="holdout")
    assert [e.doc_key for e in holdout] == [KEY_B]


@pytest.mark.asyncio
async def test_label_source_counts_expose_judge_contamination():
    """The leaderboard warns above 50% judge-labeled — it needs the split."""
    store = FakeEvalExampleStore()
    await store.save(_example(KEY_A, label_source="judge"))
    await store.save(_example(KEY_B, label_source="human"))
    await store.save(_example("c" * 64, label_source="consensus"))

    counts = await store.count_by_label_source("es1")
    assert counts == {"judge": 1, "human": 1, "consensus": 1}


@pytest.mark.asyncio
async def test_run_carries_eval_columns():
    """The five new `runs` columns must survive create → update → get. If the
    select list misses one it vanishes silently — `runs` is raw SQL, so the
    type checker will not catch it."""
    store = FakeRunStore()
    run_id = await store.create("pl1")
    fresh = await store.get(run_id)
    for col in ("eval_set_id", "labels_version", "config_digest", "sweep_id", "scores"):
        assert col in fresh, f"{col} missing from a freshly created run"

    await store.update(
        run_id,
        eval_set_id="es1",
        labels_version=3,
        config_digest="d" * 64,
        sweep_id="sw1",
        scores={"macro_f1": 0.91, "n": 42},
    )
    got = await store.get(run_id)
    assert got["eval_set_id"] == "es1"
    assert got["labels_version"] == 3
    assert got["config_digest"] == "d" * 64
    assert got["sweep_id"] == "sw1"
    assert got["scores"]["macro_f1"] == 0.91


@pytest.mark.asyncio
async def test_list_for_eval_set_is_newest_first_and_paged():
    store = FakeRunStore()
    ids = []
    for _ in range(3):
        rid = await store.create("pl1")
        await store.update(rid, eval_set_id="es1")
        ids.append(rid)
    other = await store.create("pl1")
    await store.update(other, eval_set_id="es2")

    rows = await store.list_for_eval_set("es1")
    assert [r["id"] for r in rows] == list(reversed(ids))
    assert len(await store.list_for_eval_set("es1", limit=2)) == 2
