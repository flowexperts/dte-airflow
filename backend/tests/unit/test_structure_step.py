import pandas as pd

"""The `structure` step — blocks in, the user's declared data model out.

This is the op that earns plan 050. Once it runs, the row is ordinary tabular
data and every existing step works on it unchanged.

No test here makes a network call. The `regex` provider is genuinely
deterministic; the model-backed providers are exercised through a stub. A test
that hits a real API would be slow, flaky, and billable — and CI must stay
free.
"""

import pytest

from dte.models.pipeline import StructureStep
from dte.providers import UnknownProvider, structure_provider
from dte.providers.base import Block, DataModel, FieldSpec
from dte.providers.schema import coerce_value, json_schema_for


def _model(**overrides) -> DataModel:
    return DataModel(
        fields=[
            FieldSpec(name="invoice_total", type="float", description="grand total"),
            FieldSpec(name="issued_on", type="date", description="issue date"),
            FieldSpec(name="vendor_name", type="string", description="who billed us"),
        ],
        **overrides,
    )


# ── JSON Schema derivation ──────────────────────────────────────────────────


def test_schema_has_a_property_per_declared_field():
    schema = json_schema_for(_model())
    assert set(schema["properties"]) == {"invoice_total", "issued_on", "vendor_name"}


def test_schema_forbids_additional_properties():
    """The API rejects a schema without this, and it stops a model inventing
    columns the pipeline has no place to put."""
    assert json_schema_for(_model())["additionalProperties"] is False


def test_schema_carries_descriptions_through():
    props = json_schema_for(_model())["properties"]
    assert props["invoice_total"]["description"] == "grand total"


def test_only_required_fields_are_required():
    model = DataModel(fields=[
        FieldSpec(name="a", type="string", required=True),
        FieldSpec(name="b", type="string", required=False),
    ])
    assert json_schema_for(model)["required"] == ["a"]


def test_nullable_when_not_required():
    """A model that can't find an optional value must be able to say so —
    otherwise it invents one, and a hallucination is worse than a null."""
    model = DataModel(fields=[FieldSpec(name="b", type="int", required=False)])
    assert "null" in json_schema_for(model)["properties"]["b"]["type"]


def test_unsupported_json_schema_constraints_are_not_emitted():
    """Structured outputs rejects minLength/maximum/etc. Emitting them would
    400 on the first real call."""
    schema = json_schema_for(_model())
    flat = str(schema)
    for banned in ("minLength", "maxLength", "minimum", "maximum", "multipleOf"):
        assert banned not in flat


# ── type coercion ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,type_,expected",
    [
        ("1240.50", "float", 1240.50),
        (1240, "float", 1240.0),
        ("42", "int", 42),
        ("true", "boolean", True),
        ("2024-03-01", "string", "2024-03-01"),
        (None, "float", None),
        ("", "float", None),
    ],
)
def test_coerce_value(raw, type_, expected):
    assert coerce_value(raw, type_) == expected


def test_uncoercible_value_becomes_null_not_an_exception():
    """A model returning garbage for one field costs that cell, not the run."""
    assert coerce_value("not a number", "float") is None


# ── regex provider (deterministic, free) ────────────────────────────────────


def _blocks(text: str) -> list[Block]:
    return [Block(text=text, index=0, page=1)]


def test_regex_provider_extracts_declared_patterns():
    model = DataModel(fields=[
        FieldSpec(name="invoice_total", type="float",
                  pattern=r"Total:\s*\$?([\d,]+\.\d{2})"),
        FieldSpec(name="po_number", type="string", pattern=r"PO[- ]?(\d{5})"),
    ])
    result = structure_provider("regex").structure(
        _blocks("Invoice\nTotal: $1,240.50\nPO-88123\n"), model, {}
    )
    assert result.values["invoice_total"] == 1240.50
    assert result.values["po_number"] == "88123"
    assert result.error is None


def test_regex_provider_emits_provenance_for_every_hit():
    """Provenance is mandatory of every provider, deterministic ones included."""
    model = DataModel(fields=[
        FieldSpec(name="total", type="float", pattern=r"Total:\s*([\d.]+)"),
    ])
    result = structure_provider("regex").structure(_blocks("Total: 99.50"), model, {})
    prov = result.provenance["total"]
    assert prov["page"] == 1
    assert prov["quote"] == "99.50"
    assert prov["char_start"] < prov["char_end"]
    assert result.blocks_text[prov["char_start"]:prov["char_end"]] == "99.50"


def test_regex_provider_returns_null_when_no_match():
    model = DataModel(fields=[FieldSpec(name="x", type="string", pattern=r"ZZZ(\d+)")])
    result = structure_provider("regex").structure(_blocks("nothing here"), model, {})
    assert result.values["x"] is None
    assert result.provenance["x"] is None


def test_regex_provider_requires_a_pattern_per_field():
    model = DataModel(fields=[FieldSpec(name="x", type="string")])
    result = structure_provider("regex").structure(_blocks("text"), model, {})
    assert result.error is not None
    assert "pattern" in result.error


def test_regex_provider_is_deterministic():
    model = DataModel(fields=[
        FieldSpec(name="t", type="float", pattern=r"Total:\s*([\d.]+)"),
    ])
    p = structure_provider("regex")
    runs = [p.structure(_blocks("Total: 12.00"), model, {}).values for _ in range(5)]
    assert all(r == runs[0] for r in runs)


# ── registry ────────────────────────────────────────────────────────────────


def test_unknown_structure_provider_names_alternatives():
    with pytest.raises(UnknownProvider) as exc:
        structure_provider("nonesuch")
    assert "regex" in str(exc.value)


def test_model_backed_providers_are_registered():
    from dte.providers import list_structure_providers

    assert {"claude", "openai", "regex"} <= set(list_structure_providers())


# ── the step model ──────────────────────────────────────────────────────────


def test_structure_step_parses():
    step = StructureStep(
        op="structure",
        provider="regex",
        model={"fields": [{"name": "x", "type": "string", "pattern": "(x)"}]},
    )
    assert step.model.fields[0].name == "x"


def test_structure_step_rejects_an_empty_data_model():
    """A structure step with no declared fields produces no columns — it is
    always a mistake, and better caught at save time than at run time."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        StructureStep(op="structure", provider="regex", model={"fields": []})


def test_structure_step_rejects_duplicate_field_names():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        StructureStep(
            op="structure", provider="regex",
            model={"fields": [
                {"name": "x", "type": "string"}, {"name": "x", "type": "int"},
            ]},
        )


def test_structure_step_rejects_temperature_in_params():
    """`temperature` returns a 400 on Claude Opus 5 and Sonnet 5. Catching it
    at model-parse time turns a runtime failure on every row into a clear
    validation error at save."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc:
        StructureStep(
            op="structure", provider="claude",
            model={"fields": [{"name": "x", "type": "string"}]},
            params={"temperature": 0},
        )
    assert "temperature" in str(exc.value)


def test_structure_step_rejects_api_key_in_params():
    """Step params are plaintext JSONB copied into every revision. Keys are
    Airflow connections (plan 072)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc:
        StructureStep(
            op="structure", provider="claude",
            model={"fields": [{"name": "x", "type": "string"}]},
            params={"api_key": "sk-ant-x"},
        )
    assert "connection_id" in str(exc.value)


def test_structure_step_carries_a_connection_id():
    step = StructureStep(
        op="structure", provider="claude", connection_id="anthropic_billing",
        model={"fields": [{"name": "x", "type": "string"}]},
    )
    assert step.connection_id == "anthropic_billing"
    assert StructureStep(
        op="structure", model={"fields": [{"name": "x", "type": "string"}]},
    ).connection_id is None


# ── end to end through the compiler ─────────────────────────────────────────


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("DTE_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    from dte.engine.duckdb_engine import DuckDBEngine

    return DuckDBEngine()


def _meta(row):
    """structure_meta is a JSON-encoded string column."""
    import json as _json

    return _json.loads(row["structure_meta"])


def _pipeline(steps):
    from dte.models.pipeline import Pipeline

    return Pipeline(id="p", name="p", sources=["s"], output_id="o", steps=steps)


REGEX_STEP = {
    "op": "structure", "provider": "regex",
    "model": {"fields": [
        {"name": "total", "type": "float", "pattern": r"Total:\s*\$?([\d,]+\.\d{2})"},
        {"name": "vendor", "type": "string", "pattern": r"Vendor:\s*(\w+)"},
    ]},
}


def _bind(engine, rows):
    """Register rows on the engine's connection.

    A bare `ibis.memtable` has no backend, and compile_pipeline's
    single-backend check needs one — real pipelines always come from a loaded
    source, so binding here matches production.
    """

    import ibis

    name = f"_t{next(_bind.seq)}"
    engine.con.create_table(name, ibis.memtable(rows), overwrite=True)
    return engine.con.table(name)


_bind.seq = __import__("itertools").count()


def _rows(engine, texts):
    from dte.compiler.ibis_compiler import compile_pipeline

    table = _bind(engine, [{"content": t, "doc": i} for i, t in enumerate(texts)])
    return compile_pipeline(
        _pipeline([REGEX_STEP]), {"s": table}, engine=engine
    ).execute()


def test_structure_adds_declared_columns(engine):
    df = _rows(engine, ["Vendor: Acme\nTotal: $1,240.50"])
    assert df.iloc[0]["total"] == 1240.50
    assert df.iloc[0]["vendor"] == "Acme"


def test_structure_preserves_upstream_columns(engine):
    df = _rows(engine, ["Total: $1.00\nVendor: X"])
    assert "doc" in df.columns and "content" in df.columns


def test_structure_does_not_fan_out(engine):
    """Unlike extract, structure is one row in, one row out."""
    assert len(_rows(engine, ["Total: $1.00", "Total: $2.00", "Total: $3.00"])) == 3


def test_structure_emits_per_field_provenance(engine):
    df = _rows(engine, ["Vendor: Acme\nTotal: $9.99"])
    meta = _meta(df.iloc[0])
    assert meta["fields"]["total"]["quote"] == "9.99"
    assert meta["error"] is None


def test_missing_values_are_null_not_invented(engine):
    df = _rows(engine, ["nothing useful here"])
    # NULL, not invented. The columns are typed now (float, string), so
    # pandas shows their NULLs as NaN; a typeless column used to show None.
    assert pd.isna(df.iloc[0]["total"])
    assert pd.isna(df.iloc[0]["vendor"])


def test_blank_input_is_recorded_not_raised(engine):
    df = _rows(engine, ["   "])
    assert _meta(df.iloc[0])["error"] is not None


def test_structure_is_cached_across_runs(engine, tmp_path, monkeypatch):
    """The assertion that makes prompt iteration affordable."""
    from dte.engine.duckdb_engine import DuckDBEngine

    first = _rows(engine, ["Vendor: Acme\nTotal: $5.00"])
    assert not _meta(first.iloc[0])["cached"]

    second = _rows(DuckDBEngine(), ["Vendor: Acme\nTotal: $5.00"])
    assert _meta(second.iloc[0])["cached"]
    assert second.iloc[0]["total"] == first.iloc[0]["total"]


def test_identical_text_shares_one_cache_entry(engine):
    """Content-addressed on the text — two documents whose pages read the same
    are one call, not two."""
    df = _rows(engine, ["Total: $7.00\nVendor: Z", "Total: $7.00\nVendor: Z"])
    cached = [_meta(r)["cached"] for _, r in df.iterrows()]
    assert cached.count(False) == 1 and cached.count(True) == 1


def test_changing_the_data_model_busts_the_cache(engine):
    """Field descriptions steer the model, so they belong in the cache key."""
    from dte.compiler.ibis_compiler import compile_pipeline

    table = _bind(engine, [{"content": "Total: $3.00"}])
    step_b = {
        "op": "structure", "provider": "regex",
        "model": {"fields": [
            {"name": "total", "type": "float", "description": "changed!",
             "pattern": r"Total:\s*\$?([\d,]+\.\d{2})"},
        ]},
    }
    compile_pipeline(_pipeline([REGEX_STEP]), {"s": table}, engine=engine).execute()
    df = compile_pipeline(_pipeline([step_b]), {"s": table}, engine=engine).execute()
    assert not _meta(df.iloc[0])["cached"]


def test_enrichment_stats_are_reported(engine):
    """Cost accounting: the caller must be able to see calls vs cache hits."""
    from dte.compiler.ibis_compiler import compile_pipeline

    seen = {}
    table = _bind(engine, [{"content": "Total: $1.00"}, {"content": "Total: $2.00"}])
    compile_pipeline(
        _pipeline([REGEX_STEP]), {"s": table}, engine=engine,
        on_enrichment_stats=lambda idx, s: seen.update(s),
    ).execute()
    assert seen["calls"] == 2 and seen["cached"] == 0
    assert seen["provider"] == "regex"


def test_downstream_steps_work_on_structured_columns(engine):
    """The whole point of the split: after structure, it's ordinary data."""
    from dte.compiler.ibis_compiler import compile_pipeline

    table = _bind(engine, [
        {"content": "Vendor: A\nTotal: $10.00"},
        {"content": "Vendor: B\nTotal: $99.00"},
    ])
    df = compile_pipeline(
        _pipeline([REGEX_STEP, {"op": "filter", "expr": "total > 50"}]),
        {"s": table}, engine=engine,
    ).execute()
    assert len(df) == 1 and df.iloc[0]["vendor"] == "B"


# ── model clients come from Airflow connections (plan 072) ──────────────────


class _StubModelProvider:
    """Stands in for claude: records the client it was handed."""

    name = "claude"
    _default_model = "stub"

    def __init__(self):
        self.clients = []

    def structure(self, blocks, model, params, client=None):
        from dte.providers.base import StructureResult

        self.clients.append(client)
        return StructureResult(
            values={"total": 1.0}, provenance={"total": None}, provider="claude",
            blocks_text=blocks[0].text,
        )


CLAUDE_STEP = {
    "op": "structure", "provider": "claude", "connection_id": "anthropic_billing",
    "model": {"fields": [{"name": "total", "type": "float"}]},
}


def _claude_rows(engine, texts):
    from dte.compiler.ibis_compiler import compile_pipeline

    table = _bind(engine, [{"content": t, "doc": i} for i, t in enumerate(texts)])
    return compile_pipeline(
        _pipeline([CLAUDE_STEP]), {"s": table}, engine=engine
    ).execute()


def test_model_client_is_resolved_once_per_step_and_injected(engine, monkeypatch):
    provider = _StubModelProvider()
    resolved = []
    client = object()

    def _client(name, conn_id):
        resolved.append((name, conn_id))
        return client

    monkeypatch.setattr("dte.providers.structure_provider", lambda name: provider)
    monkeypatch.setattr("dte.airflow.connections.model_client", _client)

    _claude_rows(engine, ["a", "b", "c"])
    assert resolved == [("claude", "anthropic_billing")]
    assert provider.clients == [client, client, client]


def test_missing_model_connection_fails_before_any_row(engine, monkeypatch):
    from dte.airflow.connections import ModelConnectionMissing
    from dte.compiler.ibis_compiler import CompilerError

    provider = _StubModelProvider()

    def _missing(name, conn_id):
        raise ModelConnectionMissing(f"airflow connection {conn_id!r} not found")

    monkeypatch.setattr("dte.providers.structure_provider", lambda name: provider)
    monkeypatch.setattr("dte.airflow.connections.model_client", _missing)

    with pytest.raises(CompilerError, match="anthropic_billing"):
        _claude_rows(engine, ["a"])
    assert provider.clients == []


def test_regex_never_touches_airflow(engine, monkeypatch):
    monkeypatch.setattr(
        "dte.airflow.connections.model_client",
        lambda *a: pytest.fail("regex resolved a model connection"),
    )
    _rows(engine, ["Total: $1.00"])
