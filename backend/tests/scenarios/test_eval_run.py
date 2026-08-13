"""End-to-end eval harness: label a corpus, score a config, rank it.

Hermetic by construction — the `regex` structure provider means no API key,
no network, and no cost, so CI runs the same path a user clicks through.

The assertion that matters most in this file is
`test_rerunning_the_same_config_reproduces_the_score`. Extraction is not
deterministic in general, but *scoring* must be: if the same config over the
same labels yields a different number on a cached re-run, every comparison the
leaderboard renders is noise and the harness is not worth having.
"""
from __future__ import annotations

import hashlib

import pytest

from tests.fixtures.pdf_builder import build_pdf
from tests.scenarios.helpers import create_pipeline, create_source, trigger_and_wait

pytestmark = pytest.mark.scenario


INVOICES = {
    "inv-1001.pdf": "ACME Freight\nInvoice INV-1001\nTotal: $1,240.50\n",
    "inv-1002.pdf": "ACME Freight\nInvoice INV-1002\nTotal: $87.00\n",
    "inv-1003.pdf": "Globex Corp\nInvoice INV-1003\nTotal: $9,999.99\n",
}

# What a correct extractor should produce. Deliberately written in a
# *different* format than the PDF text ("1240.50" vs "$1,240.50") so the run
# only passes if the comparators normalise, not because the strings happen to
# be identical.
TRUTH = {
    "inv-1001.pdf": {"invoice_no": "INV-1001", "total": "1240.50"},
    "inv-1002.pdf": {"invoice_no": "INV-1002", "total": "87"},
    "inv-1003.pdf": {"invoice_no": "INV-1003", "total": "9999.99"},
}

FIELD_SPECS = [
    {"name": "invoice_no", "type": "string", "description": "the invoice number"},
    {"name": "total", "type": "numeric", "description": "the invoice total"},
]


@pytest.fixture
def invoices_dir(tmp_path):
    d = tmp_path / "invoices"
    d.mkdir()
    for name, body in INVOICES.items():
        (d / name).write_bytes(build_pdf([body]))
    return d


@pytest.fixture
def doc_keys(invoices_dir) -> dict[str, str]:
    """`doc_key` is sha256 of the document bytes — the artifact store's key.
    Computing it the same way here is what makes the join real rather than a
    fixture that agrees with itself."""
    return {
        name: hashlib.sha256((invoices_dir / name).read_bytes()).hexdigest()
        for name in INVOICES
    }


def _steps(pattern_total=r"Total: \$([\d,.]+)") -> list[dict]:
    return [
        {
            "op": "extract",
            "source_field": "path",
            "provider": "pdfplumber",
            "granularity": "page",
            "output_field": "content",
            "params": {},
        },
        {
            "op": "structure",
            "input_field": "content",
            "provider": "regex",
            "on_error": "null",
            "params": {},
            "model": {
                "instructions": "",
                "fields": [
                    {
                        "name": "invoice_no", "type": "string", "required": False,
                        "description": "the invoice number",
                        "pattern": r"Invoice (INV-\d+)",
                    },
                    {
                        "name": "total", "type": "string", "required": False,
                        "description": "the invoice total",
                        "pattern": pattern_total,
                    },
                ],
            },
        },
    ]


async def _make_eval_set(client, scenario_ids, source_id: str, **over) -> str:
    es_id = scenario_ids("eval_set", "invoices")
    r = await client.post("/api/eval-sets", json={
        "id": es_id,
        "name": "invoice extraction",
        "source_id": source_id,
        "field_specs": over.pop("field_specs", FIELD_SPECS),
        **over,
    })
    assert r.status_code == 201, r.text
    return es_id


async def _label(client, es_id: str, doc_keys: dict, names=None, **over):
    for name in (names or TRUTH):
        r = await client.post(f"/api/eval-sets/{es_id}/examples", json={
            "doc_key": doc_keys[name],
            "doc_ref": name,
            "labels": TRUTH[name],
            "label_source": over.get("label_source", "human"),
            "split": over.get("split", "train"),
        })
        assert r.status_code == 201, r.text


async def _wire(client, scenario_ids, invoices_dir, steps=None):
    src = scenario_ids("source", "invoices")
    pipe = scenario_ids("pipeline", "eval")
    await create_source(
        client, id=src, source_type="documents", connection_id="local_fs",
        config={"bucket_url": str(invoices_dir), "file_glob": "**/*.pdf"},
        table="invoices",
    )
    await create_pipeline(
        client, id=pipe, sources=[src], steps=steps or _steps(),
        pipeline_type="eval",
    )
    return src, pipe


# ── the happy path ───────────────────────────────────────────────────────


async def test_full_eval_run_scores_a_perfect_config(
    client, scenario_ids, invoices_dir, doc_keys
):
    src, pipe = await _wire(client, scenario_ids, invoices_dir)
    es_id = await _make_eval_set(client, scenario_ids, src)
    await _label(client, es_id, doc_keys)

    run = await trigger_and_wait(client, pipe, eval_set_id=es_id)
    assert run["status"] == "completed", run.get("error")

    scores = run["scores"]
    assert scores["n"] == 3
    assert scores["macro_f1"] == 1.0
    assert run["eval_set_id"] == es_id
    assert len(run["config_digest"]) == 64
    by_field = {f["name"]: f for f in scores["fields"]}
    assert by_field["total"]["tp"] == 3
    assert by_field["invoice_no"]["tp"] == 3


async def test_a_broken_pattern_scores_zero_not_none(
    client, scenario_ids, invoices_dir, doc_keys
):
    """The regex matches nothing, so the extractor abstains on every row. That
    must score 0, not read as 'unrated' — an extractor that answers nothing is
    the exact case the metrics exist to catch."""
    src, pipe = await _wire(
        client, scenario_ids, invoices_dir, steps=_steps(pattern_total=r"NOPE (\d+)")
    )
    es_id = await _make_eval_set(client, scenario_ids, src)
    await _label(client, es_id, doc_keys)

    run = await trigger_and_wait(client, pipe, eval_set_id=es_id)
    assert run["status"] == "completed", run.get("error")

    by_field = {f["name"]: f for f in run["scores"]["fields"]}
    assert by_field["total"]["f1"] == 0.0
    assert by_field["total"]["fn"] == 3
    assert by_field["total"]["tp"] == 0
    # The other field still worked — macro-F1 averages them.
    assert by_field["invoice_no"]["f1"] == 1.0
    assert run["scores"]["macro_f1"] == pytest.approx(0.5)


async def test_rerunning_the_same_config_reproduces_the_score(
    client, scenario_ids, invoices_dir, doc_keys
):
    """Same config, same labels, same score — and the same digest.

    If this ever fails, scoring is not deterministic and every number the
    leaderboard shows is unreliable. This is the load-bearing assertion of the
    whole harness.
    """
    src, pipe = await _wire(client, scenario_ids, invoices_dir)
    es_id = await _make_eval_set(client, scenario_ids, src)
    await _label(client, es_id, doc_keys)

    first = await trigger_and_wait(client, pipe, eval_set_id=es_id)
    second = await trigger_and_wait(client, pipe, eval_set_id=es_id)

    assert first["config_digest"] == second["config_digest"]
    assert first["scores"]["macro_f1"] == second["scores"]["macro_f1"]
    assert first["scores"]["n"] == second["scores"]["n"]
    assert first["scores"]["fields"] == second["scores"]["fields"]


async def test_unlabeled_documents_are_not_counted_as_misses(
    client, scenario_ids, invoices_dir, doc_keys
):
    """Only one of three invoices is labeled. The other two are not failures —
    they are the labeler's backlog, and counting them would make an unlabeled
    corpus look like a broken extractor."""
    src, pipe = await _wire(client, scenario_ids, invoices_dir)
    es_id = await _make_eval_set(client, scenario_ids, src)
    await _label(client, es_id, doc_keys, names=["inv-1001.pdf"])

    run = await trigger_and_wait(client, pipe, eval_set_id=es_id)
    assert run["scores"]["n"] == 1
    assert run["scores"]["macro_f1"] == 1.0
    assert run["scores"]["documents_produced"] == 3


# ── guardrails ───────────────────────────────────────────────────────────


async def test_eval_pipeline_without_eval_set_is_rejected(
    client, scenario_ids, invoices_dir
):
    """A run with no corpus would compile, produce rows, and measure nothing —
    a green run that scored zero documents."""
    _src, pipe = await _wire(client, scenario_ids, invoices_dir)
    r = await client.post(f"/api/pipelines/{pipe}/trigger", json={})
    assert r.status_code == 422
    assert "eval_set_id" in str(r.json())


async def test_eval_pipeline_requires_a_structure_step(client, scenario_ids, invoices_dir):
    src = scenario_ids("source", "nostructure")
    await create_source(
        client, id=src, source_type="documents", connection_id="local_fs",
        config={"bucket_url": str(invoices_dir), "file_glob": "**/*.pdf"},
        table="invoices",
    )
    r = await client.post("/api/pipelines", json={
        "id": scenario_ids("pipeline", "nostructure"),
        "name": "no structure",
        "sources": [src],
        "steps": [_steps()[0]],           # extract only
        "pipeline_type": "eval",
    })
    assert r.status_code == 422
    assert "structure" in str(r.json())


async def test_labeling_an_undeclared_field_is_rejected(
    client, scenario_ids, invoices_dir, doc_keys
):
    """A label for a field the set doesn't declare is scored against nothing.
    Accepting it silently reads to the labeler as if the work was saved."""
    src, _pipe = await _wire(client, scenario_ids, invoices_dir)
    es_id = await _make_eval_set(client, scenario_ids, src)
    r = await client.post(f"/api/eval-sets/{es_id}/examples", json={
        "doc_key": doc_keys["inv-1001.pdf"],
        "labels": {"total": "1", "shipping_address": "somewhere"},
        "label_source": "human",
    })
    assert r.status_code == 422
    assert "shipping_address" in str(r.json())


async def test_a_filename_as_doc_key_is_rejected(client, scenario_ids, invoices_dir):
    src, _pipe = await _wire(client, scenario_ids, invoices_dir)
    es_id = await _make_eval_set(client, scenario_ids, src)
    r = await client.post(f"/api/eval-sets/{es_id}/examples", json={
        "doc_key": "invoices/inv-1001.pdf",
        "labels": {"total": "1"},
    })
    assert r.status_code == 422


# ── labels_version and the leaderboard ───────────────────────────────────


async def test_editing_a_label_marks_prior_runs_stale(
    client, scenario_ids, invoices_dir, doc_keys
):
    """Runs scored against older labels are shown but never ranked. Silently
    comparing across a label edit is how an eval system starts lying."""
    src, pipe = await _wire(client, scenario_ids, invoices_dir)
    es_id = await _make_eval_set(client, scenario_ids, src)
    await _label(client, es_id, doc_keys)
    await trigger_and_wait(client, pipe, eval_set_id=es_id)

    board = (await client.get(f"/api/eval-sets/{es_id}/leaderboard")).json()
    assert len(board["ranking"]) == 1
    assert board["entries"][0]["stale"] is False

    # Relabel one document — bumps labels_version.
    r = await client.post(f"/api/eval-sets/{es_id}/examples", json={
        "doc_key": doc_keys["inv-1001.pdf"],
        "labels": {"invoice_no": "INV-1001", "total": "999.00"},
        "label_source": "human",
    })
    assert r.status_code == 201

    board = (await client.get(f"/api/eval-sets/{es_id}/leaderboard")).json()
    assert board["entries"][0]["stale"] is True
    assert board["ranking"] == []


async def test_leaderboard_reports_close_configs_as_tied(
    client, scenario_ids, invoices_dir, doc_keys
):
    """Two configs on n=3 cannot be distinguished. Ranking them 1 and 2 would
    render sampling noise as a decision."""
    src, pipe_a = await _wire(client, scenario_ids, invoices_dir)
    es_id = await _make_eval_set(client, scenario_ids, src)
    await _label(client, es_id, doc_keys)

    pipe_b = scenario_ids("pipeline", "eval-b")
    await create_pipeline(
        client, id=pipe_b, sources=[src], pipeline_type="eval",
        steps=_steps(pattern_total=r"Total:\s+\$([\d,.]+)"),
    )

    await trigger_and_wait(client, pipe_a, eval_set_id=es_id)
    await trigger_and_wait(client, pipe_b, eval_set_id=es_id)

    board = (await client.get(f"/api/eval-sets/{es_id}/leaderboard")).json()
    ranks = {e["rank"] for e in board["ranking"]}
    assert len(board["ranking"]) == 2
    assert ranks == {1}, "overlapping intervals must share rank 1"


async def test_judge_labeled_majority_is_warned_about(
    client, scenario_ids, invoices_dir, doc_keys
):
    src, _pipe = await _wire(client, scenario_ids, invoices_dir)
    es_id = await _make_eval_set(client, scenario_ids, src)
    await _label(client, es_id, doc_keys, label_source="judge")

    detail = (await client.get(f"/api/eval-sets/{es_id}")).json()
    assert detail["label_sources"] == {"judge": 3}
    assert "judge" in detail["judge_labeled_warning"]


async def test_holdout_is_scored_separately(
    client, scenario_ids, invoices_dir, doc_keys
):
    src, pipe = await _wire(client, scenario_ids, invoices_dir)
    es_id = await _make_eval_set(client, scenario_ids, src)
    await _label(client, es_id, doc_keys, names=["inv-1001.pdf", "inv-1002.pdf"])
    await _label(client, es_id, doc_keys, names=["inv-1003.pdf"], split="holdout")

    run = await trigger_and_wait(client, pipe, eval_set_id=es_id)
    assert run["scores"]["n"] == 2
    assert run["scores"]["holdout"]["n"] == 1
    assert run["scores"]["holdout"]["macro_f1"] == 1.0


# ── failure drill-down ───────────────────────────────────────────────────


async def test_field_failures_lists_expected_vs_actual(
    client, scenario_ids, invoices_dir, doc_keys
):
    src, pipe = await _wire(client, scenario_ids, invoices_dir)
    es_id = await _make_eval_set(client, scenario_ids, src)
    await _label(client, es_id, doc_keys)
    # Corrupt one label so exactly one document fails on `total`.
    await client.post(f"/api/eval-sets/{es_id}/examples", json={
        "doc_key": doc_keys["inv-1002.pdf"],
        "labels": {"invoice_no": "INV-1002", "total": "12345.00"},
        "label_source": "human",
    })

    await trigger_and_wait(client, pipe, eval_set_id=es_id)
    r = await client.get(f"/api/eval-sets/{es_id}/fields/total/failures")
    assert r.status_code == 200
    failures = r.json()["failures"]
    assert len(failures) == 1
    assert failures[0]["doc_key"] == doc_keys["inv-1002.pdf"]
    assert failures[0]["expected"] == "12345.00"
    assert "87" in str(failures[0]["actual"])


# ── import ───────────────────────────────────────────────────────────────


async def test_csv_import_creates_labels(client, scenario_ids, invoices_dir, doc_keys):
    src, _pipe = await _wire(client, scenario_ids, invoices_dir)
    es_id = await _make_eval_set(client, scenario_ids, src)

    csv_body = "doc_key,invoice_no,total\n" + "\n".join(
        f"{doc_keys[n]},{TRUTH[n]['invoice_no']},{TRUTH[n]['total']}" for n in TRUTH
    )
    r = await client.post(f"/api/eval-sets/{es_id}/examples:import", json={
        "format": "csv", "content": csv_body,
    })
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 3
    assert r.json()["errors"] == []

    listing = (await client.get(f"/api/eval-sets/{es_id}/examples")).json()
    assert listing["total"] == 3
    assert {e["label_source"] for e in listing["examples"]} == {"imported"}


async def test_import_reports_bad_rows_without_discarding_good_ones(
    client, scenario_ids, invoices_dir, doc_keys
):
    src, _pipe = await _wire(client, scenario_ids, invoices_dir)
    es_id = await _make_eval_set(client, scenario_ids, src)

    csv_body = (
        "doc_key,invoice_no,total\n"
        f"{doc_keys['inv-1001.pdf']},INV-1001,1240.50\n"
        "not-a-hash,INV-9999,1.00\n"
    )
    r = await client.post(f"/api/eval-sets/{es_id}/examples:import", json={
        "format": "csv", "content": csv_body,
    })
    body = r.json()
    assert body["imported"] == 1
    assert len(body["errors"]) == 1
    assert body["errors"][0]["row"] == 1


# ── sweeps ───────────────────────────────────────────────────────────────


async def test_sweep_preflight_enqueues_nothing(client, scenario_ids, invoices_dir, doc_keys):
    """Cancelling must cost nothing. The estimate is the first call; the
    enqueue only happens on an explicit confirm."""
    src, pipe = await _wire(client, scenario_ids, invoices_dir)
    es_id = await _make_eval_set(client, scenario_ids, src)
    await _label(client, es_id, doc_keys)

    r = await client.post(f"/api/eval-sets/{es_id}/sweep", json={
        "pipeline_id": pipe,
        "matrix": {"provider": ["regex", "claude"], "granularity": ["page", "document"]},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cells"] == 4
    assert body["documents"] == 3
    assert body["uncached_calls"] == 12
    assert body["enqueued"] is False

    board = (await client.get(f"/api/eval-sets/{es_id}/leaderboard")).json()
    assert board["entries"] == []


async def test_sweep_over_the_cell_cap_is_rejected(client, scenario_ids, invoices_dir):
    src, pipe = await _wire(client, scenario_ids, invoices_dir)
    es_id = await _make_eval_set(client, scenario_ids, src)

    r = await client.post(f"/api/eval-sets/{es_id}/sweep", json={
        "pipeline_id": pipe,
        "matrix": {
            "provider": [f"p{i}" for i in range(10)],
            "model": [f"m{i}" for i in range(10)],
        },
    })
    assert r.status_code == 422
    assert "cap" in str(r.json())
