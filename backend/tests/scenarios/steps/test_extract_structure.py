"""End-to-end: a directory of PDFs → extracted text → typed columns.

The `regex` structure provider is deliberate: it makes the whole flow
hermetic — no API key, no network, no cost — so CI can run the same path a
user clicks through in the builder. Model providers are covered by unit
tests against a stub.

These payloads are the exact shapes `emptyStep("extract")` /
`emptyStep("structure")` and `DocumentsSourceEditor` emit. If the builder
and the API ever drift, this file fails before a user finds out.
"""
from __future__ import annotations

import json

import pytest

from tests.fixtures.pdf_builder import build_pdf
from tests.scenarios.helpers import (
    create_destination,
    create_pipeline,
    create_source,
    read_output_file,
    trigger_and_wait,
)

pytestmark = pytest.mark.scenario


INVOICES = {
    "inv-1001.pdf": "ACME Freight\nInvoice INV-1001\nTotal: $1,240.50\n",
    "inv-1002.pdf": "ACME Freight\nInvoice INV-1002\nTotal: $87.00\n",
    "inv-1003.pdf": "ACME Freight\nInvoice INV-1003\nTotal: $9,999.99\n",
}


@pytest.fixture
def invoices_dir(tmp_path):
    d = tmp_path / "invoices"
    d.mkdir()
    for name, body in INVOICES.items():
        (d / name).write_bytes(build_pdf([body]))
    return d


def extract_step(**over) -> dict:
    return {
        "op": "extract",
        "source_field": "path",
        "provider": "pdfplumber",
        "granularity": "page",
        "output_field": "content",
        "params": {},
        **over,
    }


def structure_step(**over) -> dict:
    return {
        "op": "structure",
        "input_field": "content",
        "provider": "regex",
        "on_error": "null",
        "params": {},
        "model": {
            "instructions": "",
            "fields": [
                {
                    "name": "invoice_no",
                    "type": "string",
                    "description": "the invoice number",
                    "required": False,
                    "pattern": r"Invoice (INV-\d+)",
                },
                {
                    "name": "total",
                    "type": "float",
                    "description": "the invoice total in USD",
                    "required": False,
                    "pattern": r"Total: \$([\d,.]+)",
                },
            ],
        },
        **over,
    }


async def _wire(client, scenario_ids, invoices_dir, out_dir, steps):
    src = scenario_ids("source", "invoices")
    dest = scenario_ids("destination", "out")
    pipe = scenario_ids("pipeline", "invoices")
    out = out_dir / "invoices.json"

    await create_source(
        client,
        id=src,
        source_type="documents",
        connection_id="local_fs",
        config={"bucket_url": str(invoices_dir), "file_glob": "**/*.pdf"},
        table="invoices",
    )
    await create_destination(
        client,
        id=dest,
        connection_id="local_fs",
        config={"type": "json_file", "path": str(out)},
    )
    await create_pipeline(
        client, id=pipe, sources=[src], output_id=dest, steps=steps
    )
    return pipe, out


async def test_documents_source_lists_without_parsing(
    client, scenario_ids, invoices_dir
):
    """A documents source is listable — and its schema is file metadata, not
    document content. Nothing is opened until an extract step runs."""
    src = scenario_ids("source", "docs")
    await create_source(
        client,
        id=src,
        source_type="documents",
        connection_id="local_fs",
        config={"bucket_url": str(invoices_dir), "file_glob": "**/*.pdf"},
        table="docs",
    )
    r = await client.get(f"/api/sources/{src}/schema")
    assert r.status_code == 200, r.text
    names = {f["name"] for f in r.json()["fields"]}
    assert "path" in names, names


async def test_extract_then_structure_to_typed_columns(
    client, scenario_ids, invoices_dir, out_dir
):
    pipe, out = await _wire(
        client, scenario_ids, invoices_dir, out_dir,
        [extract_step(), structure_step()],
    )
    run = await trigger_and_wait(client, pipe)
    assert run["status"] == "completed", run.get("error")

    rows = read_output_file(out)
    assert len(rows) == 3, rows

    # The declared fields are real typed columns — floats, not strings, with
    # the thousands separator and currency symbol stripped by coercion.
    got = {(r["invoice_no"], float(r["total"])) for r in rows}
    assert got == {
        ("INV-1001", 1240.50),
        ("INV-1002", 87.00),
        ("INV-1003", 9999.99),
    }


async def test_artifact_ref_resolves_over_http_to_the_original_pdf(
    client, scenario_ids, invoices_dir, out_dir
):
    """The document inspector's entire data path, end to end.

    A row's `artifact_ref` is a promise that `GET /api/artifacts/{key}`
    returns renderable bytes. Asserting the store directly would miss the two
    ways this breaks in practice: the ref never reaching the output rows, and
    the route serving the wrong media type to a PDF viewer.
    """
    pipe, out = await _wire(
        client, scenario_ids, invoices_dir, out_dir,
        [extract_step(), {"op": "select", "fields": [{"field": "filename"}]}],
    )
    run = await trigger_and_wait(client, pipe)
    assert run["status"] == "completed", run.get("error")

    # Read the refs from the API, not the file: provenance is split off
    # before writing, so the deliverable no longer carries them.
    served = (await client.get(f"/api/runs/{run['id']}/output?limit=10")).json()
    refs = {r["artifact_ref"] for r in served["rows"]}
    assert len(refs) == 3, f"one ref per document, got {refs}"

    originals = {(invoices_dir / n).read_bytes() for n in INVOICES}
    for ref in refs:
        assert ref.startswith("artifact://"), ref
        r = await client.get(f"/api/artifacts/{ref.removeprefix('artifact://')}")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content in originals


async def test_structured_columns_are_ordinary_data_downstream(
    client, scenario_ids, invoices_dir, out_dir
):
    """The point of splitting extract from structure: after it, every
    existing step works on the result unchanged."""
    pipe, out = await _wire(
        client, scenario_ids, invoices_dir, out_dir,
        [
            extract_step(),
            structure_step(),
            {"op": "filter", "expr": "total > 100"},
            {"op": "select", "fields": [{"field": "invoice_no"}, {"field": "total"}]},
        ],
    )
    run = await trigger_and_wait(client, pipe)
    assert run["status"] == "completed", run.get("error")

    rows = read_output_file(out)
    assert {r["invoice_no"] for r in rows} == {"INV-1001", "INV-1003"}

    # The deliverable is exactly what the user asked for. System columns
    # survive the `select` inside the compiler — they have to, or the run
    # could not be inspected — but they are split off before the writer, so
    # the customer's file never carries our content hashes.
    assert set(rows[0]) == {"invoice_no", "total"}


async def test_the_run_is_inspectable_although_its_file_is_clean(
    client, scenario_ids, invoices_dir, out_dir
):
    """The two halves of the same rule, asserted together.

    Splitting provenance out of the deliverable is only correct if the run
    surface can still show it. Testing either half alone would let the other
    regress silently: a clean file with no Inspect, or a working Inspect that
    ships hashes to the customer.
    """
    pipe, out = await _wire(
        client, scenario_ids, invoices_dir, out_dir,
        [extract_step(), structure_step()],
    )
    run = await trigger_and_wait(client, pipe)
    assert run["status"] == "completed", run.get("error")

    # On disk: no plumbing.
    on_disk = read_output_file(out)
    assert not ({"artifact_ref", "extract_meta", "structure_meta"} & set(on_disk[0]))

    # Through the API the row is whole again, and carries what the inspector
    # needs: the document, the parse holding the word boxes, the provenance.
    r = await client.get(f"/api/runs/{run['id']}/output?limit=3")
    assert r.status_code == 200, r.text
    served = r.json()["rows"]
    assert len(served) == len(on_disk)

    # JSON columns arrive parsed or as strings depending on the reader, which
    # is why the frontend's `asObject()` accepts both. Mirror it here.
    def obj(v):
        return v if isinstance(v, dict) else json.loads(v)

    first = served[0]
    assert first["artifact_ref"].startswith("artifact://")
    assert obj(first["extract_meta"])["key"]
    assert obj(first["structure_meta"])["fields"]

    # Rejoined onto the right row, not merely present somewhere.
    for served_row, disk_row in zip(served, on_disk):
        assert served_row["invoice_no"] == disk_row["invoice_no"]


async def test_preview_shows_extracted_fields(
    client, scenario_ids, invoices_dir, out_dir
):
    """Preview is the fastest debugging path in the app — it must work on a
    documents pipeline, not just a tabular one."""
    pipe, _ = await _wire(
        client, scenario_ids, invoices_dir, out_dir,
        [extract_step(), structure_step()],
    )
    r = await client.get(f"/api/pipelines/{pipe}/preview?limit=10")
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    assert rows and "invoice_no" in rows[0], rows[:1]


async def test_unparseable_document_nulls_its_row_without_failing_the_run(
    client, scenario_ids, invoices_dir, out_dir
):
    """One bad PDF in a batch must not cost the batch."""
    (invoices_dir / "corrupt.pdf").write_bytes(b"%PDF-1.4 this is not a pdf")

    pipe, out = await _wire(
        client, scenario_ids, invoices_dir, out_dir,
        [extract_step(), structure_step()],
    )
    run = await trigger_and_wait(client, pipe)
    assert run["status"] == "completed", run.get("error")

    rows = read_output_file(out)
    assert len(rows) == 4, rows
    good = [r for r in rows if r.get("invoice_no")]
    bad = [r for r in rows if not r.get("invoice_no")]
    assert len(good) == 3 and len(bad) == 1


async def test_structure_step_rejects_sampling_params_at_save(
    client, scenario_ids, invoices_dir, out_dir
):
    """temperature is rejected with a 400 by the models themselves. Catching
    it at save turns a per-row runtime failure into one validation error."""
    src = scenario_ids("source", "invoices")
    dest = scenario_ids("destination", "out")
    await create_source(
        client, id=src, source_type="documents", connection_id="local_fs",
        config={"bucket_url": str(invoices_dir), "file_glob": "**/*.pdf"},
        table="invoices",
    )
    await create_destination(
        client, id=dest, connection_id="local_fs",
        config={"type": "json_file", "path": str(out_dir / "o.json")},
    )
    r = await client.post("/api/pipelines", json={
        "id": scenario_ids("pipeline", "bad"),
        "name": "bad",
        "sources": [src],
        "output_id": dest,
        "pipeline_type": "transform",
        "steps": [
            extract_step(),
            structure_step(provider="claude", params={"temperature": 0}),
        ],
    })
    assert r.status_code == 422, r.status_code
    assert "temperature" in r.text
