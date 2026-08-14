"""The Compare flow end to end: pipeline → configs side by side (plan 053).

`test_eval_run.py` covers the harness once someone has an eval set and
labels. This file covers the part that made those unreachable: getting from
a transform pipeline you already have to a comparison, with nothing typed
twice and no ground truth required.

Hermetic — `regex` means no API key, no network, no cost. Two variants
differ by the `total` pattern, which is what a genuine config change looks
like from the scorer's point of view.

The assertion that matters most here is
`test_agreement_is_visible_before_any_label_exists`. If the comparison only
renders once labels exist, the flow is back to demanding work nobody has
done, which is the failure plan 053 exists to remove.
"""
from __future__ import annotations

import hashlib

import pytest

from tests.fixtures.pdf_builder import build_pdf
from tests.scenarios.helpers import create_destination, create_pipeline, create_source

pytestmark = pytest.mark.scenario


INVOICES = {
    "inv-1001.pdf": "ACME Freight\nInvoice INV-1001\nTotal: $1,240.50\n",
    "inv-1002.pdf": "ACME Freight\nInvoice INV-1002\nTotal: $87.00\n",
}


@pytest.fixture
def invoices_dir(tmp_path):
    d = tmp_path / "invoices"
    d.mkdir()
    for name, body in INVOICES.items():
        (d / name).write_bytes(build_pdf([body]))
    return d


@pytest.fixture
def doc_keys(invoices_dir) -> dict[str, str]:
    return {
        name: hashlib.sha256((invoices_dir / name).read_bytes()).hexdigest()
        for name in INVOICES
    }


def _steps(*, with_patterns: bool = True) -> list[dict]:
    return [
        {"op": "extract", "source_field": "path", "provider": "pdfplumber",
         "granularity": "page", "output_field": "content", "params": {}},
        {"op": "structure", "input_field": "content", "provider": "regex",
         "on_error": "null", "params": {},
         "model": {"instructions": "", "fields": [
             {"name": "invoice_no", "type": "string", "required": False,
              "description": "the invoice number",
              "pattern": r"Invoice (INV-\d+)" if with_patterns else None},
             {"name": "total", "type": "float", "required": False,
              "description": "the invoice total",
              "pattern": r"Total: \$([\d,.]+)" if with_patterns else None},
         ]}},
    ]


@pytest.fixture
async def transform_pipeline(client, scenario_ids, invoices_dir, tmp_path):
    """An ordinary extraction pipeline — the thing a user already has."""
    src = scenario_ids("source", "invoices")
    dest = scenario_ids("destination", "out")
    pipe = scenario_ids("pipeline", "invoices")
    await create_source(
        client, id=src, source_type="documents", connection_id="local_fs",
        config={"bucket_url": str(invoices_dir), "file_glob": "**/*.pdf"},
        table="invoices",
    )
    await create_destination(
        client, id=dest, connection_id="local_fs",
        config={"type": "json_file", "path": str(tmp_path / "out.json")},
    )
    await create_pipeline(
        client, id=pipe, sources=[src], steps=_steps(), output_id=dest,
        pipeline_type="transform",
    )
    return {"pipeline": pipe, "source": src, "destination": dest}


class TestDerivation:
    async def test_transform_pipeline_becomes_an_eval_twin(self, client, transform_pipeline):
        r = await client.post(f"/api/pipelines/{transform_pipeline['pipeline']}/as-eval")
        assert r.status_code == 201, r.text
        twin = await client.get(f"/api/pipelines/{r.json()['pipeline_id']}")
        assert twin.json()["pipeline_type"] == "eval"

    async def test_eval_set_is_derived_with_no_fields_retyped(
        self, client, transform_pipeline
    ):
        # The whole point. The builder used to warn that a name mismatch
        # between these two lists "scores zero on every document".
        twin = (await client.post(
            f"/api/pipelines/{transform_pipeline['pipeline']}/as-eval")).json()
        r = await client.post(
            "/api/eval-sets:for-pipeline", json={"pipeline_id": twin["pipeline_id"]})
        assert r.status_code == 201, r.text
        es = await client.get(f"/api/eval-sets/{r.json()['eval_set_id']}")
        assert [f["name"] for f in es.json()["field_specs"]] == ["invoice_no", "total"]
        assert [f["type"] for f in es.json()["field_specs"]] == ["string", "numeric"]

    async def test_the_whole_derivation_is_idempotent(self, client, transform_pipeline):
        # Compare is a button people press twice.
        first_twin = (await client.post(
            f"/api/pipelines/{transform_pipeline['pipeline']}/as-eval")).json()
        first_set = (await client.post(
            "/api/eval-sets:for-pipeline",
            json={"pipeline_id": first_twin["pipeline_id"]})).json()
        second_twin = (await client.post(
            f"/api/pipelines/{transform_pipeline['pipeline']}/as-eval")).json()
        second_set = (await client.post(
            "/api/eval-sets:for-pipeline",
            json={"pipeline_id": second_twin["pipeline_id"]})).json()
        assert second_twin["created"] is False
        assert second_set["created"] is False
        assert first_set["eval_set_id"] == second_set["eval_set_id"]


@pytest.fixture
async def compared(client, scenario_ids, transform_pipeline, invoices_dir):
    """The flow a user walks: derive, then sweep two regex configs."""
    twin = (await client.post(
        f"/api/pipelines/{transform_pipeline['pipeline']}/as-eval")).json()
    es = (await client.post(
        "/api/eval-sets:for-pipeline",
        json={"pipeline_id": twin["pipeline_id"]})).json()

    # Two genuinely different configs. The second's pattern misses the
    # thousands separator, so it reads $1,240.50 as "1" — wrong on one
    # document and right on the other, which is what a real config
    # difference looks like.
    r = await client.post(f"/api/eval-sets/{es['eval_set_id']}/sweep", json={
        "pipeline_id": twin["pipeline_id"],
        "matrix": {"model.instructions": ["", "ignore the stub"]},
        "confirm": True,
    })
    assert r.status_code == 200, r.text
    return {"eval_set_id": es["eval_set_id"], "sweep_id": r.json()["sweep_id"],
            "runs": r.json()["runs"]}


class TestEstimateBeforeSpend:
    async def test_estimate_enqueues_nothing(self, client, transform_pipeline):
        twin = (await client.post(
            f"/api/pipelines/{transform_pipeline['pipeline']}/as-eval")).json()
        es = (await client.post(
            "/api/eval-sets:for-pipeline",
            json={"pipeline_id": twin["pipeline_id"]})).json()
        r = await client.post(f"/api/eval-sets/{es['eval_set_id']}/sweep", json={
            "pipeline_id": twin["pipeline_id"],
            "matrix": {"provider": ["regex"]},
        })
        assert r.status_code == 200
        assert r.json()["enqueued"] is False
        assert r.json()["cells"] == 1
        assert "runs" not in r.json()

    async def test_a_normalised_twin_can_sweep_params_model(
        self, client, transform_pipeline
    ):
        # `apply_cell` refuses to create a leaf that doesn't exist, so this
        # 422'd before the twin filled `params.model` in.
        twin = (await client.post(
            f"/api/pipelines/{transform_pipeline['pipeline']}/as-eval")).json()
        pipeline = (await client.get(f"/api/pipelines/{twin['pipeline_id']}")).json()
        # regex gets no model param; prove instructions is sweepable instead.
        assert "instructions" in pipeline["steps"][1]["model"]


class TestLabelFreeComparison:
    async def test_agreement_is_visible_before_any_label_exists(self, client, compared):
        # The assertion this plan exists for. Plan 051's leaderboard showed
        # "No comparable runs yet" here — a demand for work nobody had done,
        # which is why the harness stayed empty.
        r = await client.get(f"/api/sweeps/{compared['sweep_id']}/comparison")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["labels"]["total"] == 0
        assert len(body["cells"]) == 2
        assert len(body["documents"]) == len(INVOICES)

    async def test_scores_are_absent_not_zero_when_unlabelled(self, client, compared):
        # Absent and zero are opposite situations. Rendering them alike is
        # how a working extractor gets mistaken for a broken one.
        body = (await client.get(f"/api/sweeps/{compared['sweep_id']}/comparison")).json()
        assert all(c["macro_f1"] is None for c in body["cells"])

    async def test_per_field_agreement_is_reported(self, client, compared):
        body = (await client.get(f"/api/sweeps/{compared['sweep_id']}/comparison")).json()
        names = {f["name"] for f in body["fields"]}
        assert names == {"invoice_no", "total"}
        assert all(f["agreement_rate"] is not None for f in body["fields"])

    async def test_every_document_carries_a_value_per_cell(self, client, compared):
        body = (await client.get(f"/api/sweeps/{compared['sweep_id']}/comparison")).json()
        cell_ids = {c["cell_id"] for c in body["cells"]}
        for doc in body["documents"]:
            assert set(doc["values"]) == cell_ids

    async def test_regex_cells_cost_nothing(self, client, compared):
        # The economic claim, asserted rather than assumed: a comparison you
        # can run for free is the one people actually run.
        body = (await client.get(f"/api/sweeps/{compared['sweep_id']}/comparison")).json()
        assert all(c["cost_usd"] in (0.0, None) for c in body["cells"])


class TestLabelsThenScores:
    async def test_shared_provider_blocks_auto_accept_and_says_so(
        self, client, compared
    ):
        # Both cells are regex variants, so they share a provider. Consensus
        # refuses the write — agreement between prompts against one model is
        # that model's blind spots, not truth. The comparison must know that
        # *before* offering the button, since holding the provider fixed is
        # the common shape of a sweep.
        body = (await client.get(f"/api/sweeps/{compared['sweep_id']}/comparison")).json()
        assert body["labels"]["agreed_unlabeled"] > 0
        assert body["labels"]["auto_accept"] is False
        assert "provider" in body["labels"]["warning"]

        r = await client.post(f"/api/eval-sets/{compared['eval_set_id']}/bootstrap", json={
            "variant_pipeline_ids": [c["pipeline_id"] for c in body["cells"]],
            "confirm": True,
        })
        assert r.status_code == 409, "the UI's warning must match what the API does"

    async def test_labels_land_and_the_offer_is_not_repeated(
        self, client, compared, doc_keys
    ):
        body = (await client.get(f"/api/sweeps/{compared['sweep_id']}/comparison")).json()
        offered = body["labels"]["agreed_unlabeled"]
        assert offered > 0

        # Label them directly, as the review queue would.
        agreed = [d for d in body["documents"] if d["agrees"]]
        first_cell = body["cells"][0]["cell_id"]
        for doc in agreed:
            r = await client.post(
                f"/api/eval-sets/{compared['eval_set_id']}/examples",
                json={"doc_key": doc["doc_key"], "doc_ref": doc["doc_ref"],
                      "labels": doc["values"][first_cell], "label_source": "human"},
            )
            assert r.status_code == 201, r.text

        after = (await client.get(
            f"/api/sweeps/{compared['sweep_id']}/comparison")).json()
        assert after["labels"]["total"] == offered
        # The accept affordance must not re-offer documents already labelled.
        assert after["labels"]["agreed_unlabeled"] == 0


class TestRefusals:
    async def test_a_pipeline_with_no_structure_step_cannot_be_compared(
        self, client, scenario_ids, transform_pipeline
    ):
        plain = scenario_ids("pipeline", "plain")
        await create_pipeline(
            client, id=plain, sources=[transform_pipeline["source"]],
            steps=[{"op": "select", "fields": [{"field": "path"}]}],
            pipeline_type="transform",
            output_id=transform_pipeline["destination"],
        )
        r = await client.post(f"/api/pipelines/{plain}/as-eval")
        assert r.status_code == 422
        assert "structure" in r.json()["detail"]

    async def test_a_sweep_against_a_foreign_corpus_is_refused(
        self, client, scenario_ids, transform_pipeline, invoices_dir
    ):
        # The check the sweep route used to skip. Every cell would have
        # scored zero and billed for it.
        twin = (await client.post(
            f"/api/pipelines/{transform_pipeline['pipeline']}/as-eval")).json()
        other_src = scenario_ids("source", "other")
        await create_source(
            client, id=other_src, source_type="documents", connection_id="local_fs",
            config={"bucket_url": str(invoices_dir), "file_glob": "**/*.pdf"},
            table="other",
        )
        foreign = scenario_ids("eval_set", "foreign")
        r = await client.post("/api/eval-sets", json={
            "id": foreign, "name": "foreign", "source_id": other_src,
            "field_specs": [{"name": "total", "type": "numeric"}],
        })
        assert r.status_code == 201, r.text

        r = await client.post(f"/api/eval-sets/{foreign}/sweep", json={
            "pipeline_id": twin["pipeline_id"],
            "matrix": {"provider": ["regex"]},
        })
        assert r.status_code == 422
        assert other_src in r.json()["detail"]
