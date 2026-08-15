"""An eval set must point at a real `documents` source (plan 051).

`source_id` is the corpus. Nothing validated it at save time, so two
mistakes were accepted silently and surfaced much later as something else:

  - A **missing** source id saved fine and then failed at trigger, by which
    point the error names a pipeline the user did not think they were
    configuring.
  - A **non-documents** source (a csv, a postgres table) saved fine, ran,
    produced rows with no `artifact_ref`, joined against zero labels, and
    scored a flat zero. That reads as "the extractor is broken" when the
    real problem is that this corpus was never documents.

Both are configuration errors knowable at save time, and the second is the
expensive one — it can burn a whole sweep before anyone questions the set.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.models.pipeline import SourceCreate


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def client(fake_stores):
    c = TestClient(app)
    _run(fake_stores["source"].save(SourceCreate(
        id="docs_src", connection_id="local_fs", source_type="documents",
        config={"bucket_url": "/tmp", "file_glob": "**/*.pdf"}, table="docs",
    )))
    _run(fake_stores["source"].save(SourceCreate(
        id="csv_src", connection_id="local_fs", source_type="filesystem",
        config={"bucket_url": "/tmp", "file_glob": "**/*.csv"}, table="rows",
    )))
    return c


def _body(**over):
    body = {
        "id": "es_new",
        "name": "Invoices",
        "source_id": "docs_src",
        "field_specs": [{"name": "total", "type": "numeric"}],
    }
    body.update(over)
    return body


def test_a_documents_source_is_accepted(client):
    assert client.post("/api/eval-sets", json=_body()).status_code == 201


def test_a_missing_source_is_rejected_at_save(client):
    r = client.post("/api/eval-sets", json=_body(source_id="nope"))
    assert r.status_code == 422
    assert "nope" in r.text


def test_a_non_documents_source_is_rejected_at_save(client):
    """The expensive mistake. A filesystem source produces no artifact_ref,
    so every label joins against nothing and the set scores zero forever."""
    r = client.post("/api/eval-sets", json=_body(source_id="csv_src"))
    assert r.status_code == 422
    body = r.text
    assert "csv_src" in body
    assert "documents" in body


def test_the_rejection_names_the_source_kind_it_got(client):
    """Naming only the requirement leaves the user to guess what they picked."""
    r = client.post("/api/eval-sets", json=_body(source_id="csv_src"))
    assert "filesystem" in r.text


def test_update_enforces_the_same_rule(client):
    """A set can be repointed after creation; the rule has to hold there too
    or the validation is a speed bump rather than a guarantee."""
    assert client.post("/api/eval-sets", json=_body()).status_code == 201
    r = client.put("/api/eval-sets/es_new", json=_body(source_id="csv_src"))
    assert r.status_code == 422
