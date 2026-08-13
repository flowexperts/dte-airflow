"""Content-addressed artifact store.

Every caching claim in plans 050 and 051 rests on this: re-running a pipeline
over unchanged documents must be free, and changing a `structure` prompt must
not invalidate the `extract` output it was derived from.
"""

import pytest

from dte.artifacts import LocalArtifactStore, derived_key, doc_key, get_artifact_store


# ── key derivation ──────────────────────────────────────────────────────────


def test_doc_key_is_sha256_of_content():
    assert doc_key(b"hello") == doc_key(b"hello")
    assert doc_key(b"hello") != doc_key(b"world")
    assert len(doc_key(b"hello")) == 64          # hex sha256


def test_doc_key_is_stable_across_filenames():
    """Labels join on doc_key, so a rename or a directory move must not
    invalidate them."""
    assert doc_key(b"%PDF-1.4 invoice") == doc_key(b"%PDF-1.4 invoice")


def test_derived_key_varies_with_every_input():
    base = derived_key(doc_key(b"pdf"), "structure", "claude", {"temperature": 0})
    assert base != derived_key(doc_key(b"other"), "structure", "claude", {"temperature": 0})
    assert base != derived_key(doc_key(b"pdf"), "extract", "claude", {"temperature": 0})
    assert base != derived_key(doc_key(b"pdf"), "structure", "openai", {"temperature": 0})
    assert base != derived_key(doc_key(b"pdf"), "structure", "claude", {"temperature": 1})


def test_derived_key_is_insensitive_to_param_ordering():
    """Params are canonicalised — a dict built in a different order is the
    same cache entry, or the cache would miss constantly."""
    a = derived_key("d", "structure", "claude", {"a": 1, "b": 2})
    b = derived_key("d", "structure", "claude", {"b": 2, "a": 1})
    assert a == b


def test_derived_key_handles_nested_params():
    a = derived_key("d", "s", "p", {"model": {"fields": [{"name": "x", "type": "int"}]}})
    b = derived_key("d", "s", "p", {"model": {"fields": [{"type": "int", "name": "x"}]}})
    assert a == b


def test_changing_structure_params_does_not_change_the_extract_key():
    """The whole economic argument for the two-op split: tuning a prompt must
    not re-parse a single PDF."""
    dk = doc_key(b"%PDF-1.4")
    extract_a = derived_key(dk, "extract", "pdfplumber", {"granularity": "page"})
    extract_b = derived_key(dk, "extract", "pdfplumber", {"granularity": "page"})
    structure_a = derived_key(dk, "structure", "claude", {"prompt": "v1"})
    structure_b = derived_key(dk, "structure", "claude", {"prompt": "v2"})

    assert extract_a == extract_b        # extraction untouched
    assert structure_a != structure_b    # only the model call varies


# ── local store ─────────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path):
    return LocalArtifactStore(tmp_path / "artifacts")


def test_put_then_get_roundtrips(store):
    key = doc_key(b"payload")
    store.put(key, b"payload", "application/pdf")
    assert store.get(key) == b"payload"


def test_exists_reflects_writes(store):
    key = doc_key(b"x")
    assert not store.exists(key)
    store.put(key, b"x", "text/plain")
    assert store.exists(key)


def test_get_missing_raises(store):
    with pytest.raises(KeyError):
        store.get("0" * 64)


def test_put_is_idempotent(store):
    key = doc_key(b"same")
    first = store.put(key, b"same", "text/plain")
    second = store.put(key, b"same", "text/plain")
    assert first == second
    assert store.get(key) == b"same"


def test_media_type_round_trips(store):
    key = doc_key(b"pdfbytes")
    store.put(key, b"pdfbytes", "application/pdf")
    assert store.media_type(key) == "application/pdf"


def test_uri_is_the_artifact_scheme(store):
    """Rows carry refs, never blobs."""
    key = doc_key(b"z")
    assert store.put(key, b"z", "text/plain") == f"artifact://{key}"


def test_keys_shard_into_subdirectories(store, tmp_path):
    """A flat directory with 100k documents is a filesystem problem."""
    key = doc_key(b"shardme")
    store.put(key, b"shardme", "text/plain")
    written = list((tmp_path / "artifacts").rglob("*.bin"))
    assert len(written) == 1
    assert written[0].parent.name == key[2:4]
    assert written[0].parent.parent.name == key[0:2]


def test_rejects_malformed_keys(store):
    """Keys come from URL paths — a traversal attempt must not reach the FS."""
    for bad in ["../../etc/passwd", "not-hex", "", "a" * 63, "A" * 64 + "b"]:
        with pytest.raises(ValueError):
            store.put(bad, b"x", "text/plain")
        with pytest.raises(ValueError):
            store.get(bad)


def test_open_stream_yields_content(store):
    key = doc_key(b"streamed")
    store.put(key, b"streamed", "text/plain")
    with store.open_stream(key) as fh:
        assert fh.read() == b"streamed"


def test_store_creates_its_directory_lazily(tmp_path):
    target = tmp_path / "deep" / "nested" / "artifacts"
    s = LocalArtifactStore(target)
    assert not target.exists()          # constructing must not touch the FS
    s.put(doc_key(b"a"), b"a", "text/plain")
    assert target.exists()


# ── resolver ────────────────────────────────────────────────────────────────


def test_get_artifact_store_honours_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DTE_ARTIFACT_DIR", str(tmp_path / "from-env"))
    s = get_artifact_store()
    assert isinstance(s, LocalArtifactStore)
    key = doc_key(b"env")
    s.put(key, b"env", "text/plain")
    assert (tmp_path / "from-env").exists()
