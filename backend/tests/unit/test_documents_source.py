"""The `documents` source kind — a lazy file listing, not a parser.

The critical property: loading lists files and nothing more. Extraction
happens only when an `extract` step runs. `POST /api/schema/infer` fires
automatically from the builder, so if listing parsed PDFs, every keystroke in
the UI would cost money.
"""

import ibis
import pytest
from pydantic import ValidationError

from dte.models.pipeline import SOURCE_CONNECTION_COMPAT, Source, SourceCreate
from dte.sources.loader import load_source


def _src(tmp_path, glob="**/*.pdf", sid="docs1"):
    return Source(
        id=sid,
        connection_id="local_fs",
        source_type="documents",
        config={"bucket_url": str(tmp_path), "file_glob": glob},
        table="docs",
    )


@pytest.fixture
def corpus(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4 aaa")
    (tmp_path / "b.pdf").write_bytes(b"%PDF-1.4 bbbb")
    (tmp_path / "sub" / "c.pdf").write_bytes(b"%PDF-1.4 cc")
    (tmp_path / "ignore.txt").write_text("not a pdf")
    return tmp_path


# ── model ───────────────────────────────────────────────────────────────────


def test_documents_is_a_valid_source_kind():
    s = SourceCreate(
        id="d1", connection_id="local_fs", source_type="documents",
        config={"bucket_url": "/tmp", "file_glob": "**/*.pdf"}, table="docs",
    )
    assert s.source_type == "documents"


def test_documents_config_rejects_unknown_keys():
    with pytest.raises(ValidationError):
        SourceCreate(
            id="d2", connection_id="local_fs", source_type="documents",
            config={"bucket_url": "/tmp", "nonsense": 1}, table="docs",
        )


def test_documents_binds_to_file_shaped_connections():
    """Documents live wherever files live — local disk today, object stores
    when the remote loader lands."""
    assert "local_fs" in SOURCE_CONNECTION_COMPAT["documents"]


def test_documents_default_glob_is_pdf():
    s = SourceCreate(
        id="d3", connection_id="local_fs", source_type="documents",
        config={"bucket_url": "/tmp"}, table="docs",
    )
    assert s.config["file_glob"].endswith(".pdf")


# ── listing ─────────────────────────────────────────────────────────────────


def test_lists_one_row_per_matching_file(corpus):
    con = ibis.duckdb.connect()
    df = load_source(_src(corpus), con, {}).execute()
    assert len(df) == 3
    assert sorted(df["filename"].tolist()) == ["a.pdf", "b.pdf", "c.pdf"]


def test_listing_columns(corpus):
    con = ibis.duckdb.connect()
    table = load_source(_src(corpus), con, {})
    assert set(table.columns) >= {
        "path", "filename", "ext", "size_bytes", "modified_at", "media_type",
    }


def test_sizes_and_media_type_are_real(corpus):
    con = ibis.duckdb.connect()
    df = load_source(_src(corpus), con, {}).execute()
    row = df[df["filename"] == "a.pdf"].iloc[0]
    assert row["size_bytes"] == len(b"%PDF-1.4 aaa")
    assert row["media_type"] == "application/pdf"
    assert row["ext"] == ".pdf"


def test_glob_is_honoured(corpus):
    con = ibis.duckdb.connect()
    df = load_source(_src(corpus, glob="*.pdf"), con, {}).execute()
    # Top level only — the nested c.pdf must not appear.
    assert sorted(df["filename"].tolist()) == ["a.pdf", "b.pdf"]


def test_non_matching_files_are_excluded(corpus):
    con = ibis.duckdb.connect()
    df = load_source(_src(corpus), con, {}).execute()
    assert "ignore.txt" not in df["filename"].tolist()


def test_listing_does_not_read_file_contents(corpus):
    """A directory of unreadable files still lists — proof nothing is parsed.

    If loading ever starts opening documents, this fails loudly instead of
    quietly making schema inference cost money.
    """
    (corpus / "corrupt.pdf").write_bytes(b"\x00\x01\x02 not a pdf at all")
    con = ibis.duckdb.connect()
    df = load_source(_src(corpus), con, {}).execute()
    assert "corrupt.pdf" in df["filename"].tolist()
    assert len(df) == 4


def test_empty_directory_raises_a_named_error(tmp_path):
    con = ibis.duckdb.connect()
    with pytest.raises(FileNotFoundError) as exc:
        load_source(_src(tmp_path), con, {})
    assert "*.pdf" in str(exc.value)


def test_returns_an_ibis_table(corpus):
    con = ibis.duckdb.connect()
    assert isinstance(load_source(_src(corpus), con, {}), ibis.Table)


def test_non_pdf_extensions_are_listed_with_their_media_type(tmp_path):
    """The listing is modality-agnostic — audio and images land here too once
    their providers exist."""
    (tmp_path / "clip.mp3").write_bytes(b"ID3")
    (tmp_path / "pic.png").write_bytes(b"\x89PNG")
    con = ibis.duckdb.connect()
    df = load_source(_src(tmp_path, glob="**/*"), con, {}).execute()
    by_name = {r["filename"]: r for _, r in df.iterrows()}
    assert by_name["clip.mp3"]["media_type"] == "audio/mpeg"
    assert by_name["pic.png"]["media_type"] == "image/png"


def test_table_is_queryable_like_any_other_source(corpus):
    """Once listed, it's ordinary tabular data — every existing step works."""
    con = ibis.duckdb.connect()
    table = load_source(_src(corpus), con, {})
    big = table.filter(table.size_bytes > 12).execute()
    assert big["filename"].tolist() == ["b.pdf"]
