"""A failure is a property of the attempt, not of the input.

Reported as "the claude columns are all blank". The cause was an unset
`ANTHROPIC_API_KEY`, which is ordinary. What made it a bug is what happened
next: the auth error was written to the artifact cache alongside the null
values, keyed by `sha256(text)` plus the config. Every subsequent run then
*hit* that cache — costing nothing, calling nothing, and returning nulls —
so fixing the key changed nothing and the config looked permanently
incapable of extracting anything.

    "structure_meta": {"cached": true, "error": "claude: Could not resolve
     authentication method...", "input_tokens": 0, "fields": {...null}}

The cache exists so that re-running a config you already paid for is free.
An error is not something you paid for. Caching one converts a transient
condition — a missing key, a 429, a timeout, a five-minute outage — into a
permanent property of that document, and the run reports it as a clean,
fast, zero-cost abstention.

Both enrichment ops did it, so both are covered here.
"""
from __future__ import annotations

import json

import pytest

from dte.models.pipeline import Pipeline
from dte.providers.base import Block, StructureResult


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("DTE_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    from dte.engine.duckdb_engine import DuckDBEngine

    return DuckDBEngine()


def _bind(engine, rows):
    import ibis

    engine.con.create_table("t", ibis.memtable(rows), overwrite=True)
    return engine.con.table("t")


STEP = {
    "op": "structure", "provider": "regex", "on_error": "null", "params": {},
    "model": {"fields": [{"name": "total", "type": "float", "pattern": r"(\d+)"}]},
}


class _FlakyProvider:
    """Fails once, then succeeds — a transient outage in two calls."""

    name = "regex"

    def __init__(self):
        self.calls = 0

    def structure(self, blocks, model, params):
        self.calls += 1
        if self.calls == 1:
            return StructureResult(
                values={"total": None}, provenance={}, provider="regex",
                error="claude: Could not resolve authentication method",
                elapsed_ms=0, input_tokens=0, output_tokens=0,
            )
        return StructureResult(
            values={"total": 42.0}, provenance={}, provider="regex",
            error=None, elapsed_ms=5, input_tokens=10, output_tokens=3,
        )


@pytest.fixture
def flaky(monkeypatch):
    provider = _FlakyProvider()
    monkeypatch.setattr(
        "dte.providers.structure_provider", lambda name: provider
    )
    return provider


def _run(engine):
    from dte.compiler.ibis_compiler import compile_pipeline

    table = _bind(engine, [{"content": "Total 42", "doc": 0}])
    pipeline = Pipeline(id="p", name="p", sources=["s"], output_id="o", steps=[STEP])
    return compile_pipeline(pipeline, {"s": table}, engine=engine).execute()


def _meta(df):
    return json.loads(df.iloc[0]["structure_meta"])


class TestStructureErrorsAreNotCached:
    def test_a_failed_call_is_retried_on_the_next_run(self, engine, flaky):
        first = _run(engine)
        assert _meta(first)["error"] is not None
        assert first.iloc[0]["total"] is None

        second = _run(engine)
        # Without this, the second run is a cache hit returning the same
        # null and the same error, forever, for free.
        assert flaky.calls == 2, "the failed result was served from cache"
        assert _meta(second)["error"] is None
        assert second.iloc[0]["total"] == 42.0

    def test_a_successful_call_is_still_cached(self, engine, flaky):
        # The economic argument the cache exists for must survive the fix.
        _run(engine)          # fails, not cached
        _run(engine)          # succeeds, cached
        third = _run(engine)
        assert flaky.calls == 2, "a successful result should not be recomputed"
        assert _meta(third)["cached"] is True
        assert third.iloc[0]["total"] == 42.0

    def test_the_failing_run_reports_zero_cost_not_a_cache_hit(self, engine, flaky):
        # A failed call is not a cache hit; labelling it one hides the
        # failure inside the metric that is supposed to prove savings.
        assert _meta(_run(engine))["cached"] is False


class TestExtractErrorsAreNotCached:
    def test_a_failed_parse_is_retried_on_the_next_run(self, engine, monkeypatch):
        from dte.providers.base import ExtractResult

        calls = {"n": 0}

        class _Flaky:
            name = "pdfplumber"

            def extract(self, content, media_type, params):
                calls["n"] += 1
                if calls["n"] == 1:
                    return ExtractResult(blocks=[], provider="pdfplumber", error="transient read failure", elapsed_ms=0)
                return ExtractResult(
                    blocks=[Block(text="page one", index=0, page=1)], provider="pdfplumber", error=None, elapsed_ms=3,
                )

        monkeypatch.setattr(
            "dte.providers.extract_provider", lambda name: _Flaky()
        )
        doc = engine.con  # noqa: F841 - fixture forces artifact dir

        import ibis
        from dte.compiler.ibis_compiler import compile_pipeline

        pdf = __import__("pathlib").Path(
            __import__("os").environ["DTE_ARTIFACT_DIR"]
        ).parent / "a.pdf"
        pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(b"%PDF-1.4 fake")

        engine.con.create_table(
            "docs", ibis.memtable([{"path": str(pdf), "media_type": "application/pdf"}]),
            overwrite=True,
        )
        steps = [{"op": "extract", "source_field": "path", "provider": "pdfplumber",
                  "granularity": "page", "output_field": "content", "params": {}}]
        pipeline = Pipeline(id="p", name="p", sources=["s"], output_id="o", steps=steps)

        compile_pipeline(pipeline, {"s": engine.con.table("docs")}, engine=engine).execute()
        df = compile_pipeline(
            pipeline, {"s": engine.con.table("docs")}, engine=engine
        ).execute()

        assert calls["n"] == 2, "the failed parse was served from cache"
        assert df.iloc[0]["content"] == "page one"
