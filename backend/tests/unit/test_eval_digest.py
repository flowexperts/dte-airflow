"""`config_digest` — the identity of an extraction config (plan 051 task 8).

This is what makes drift detectable: same digest + same `labels_version` + a
different score later means the provider changed under you. Everything about
these tests is about what must and must not change the digest.
"""
from __future__ import annotations

from dte.evals.digest import config_digest
from dte.models.pipeline import Pipeline

_MODEL = {
    "fields": [
        {"name": "total", "type": "number", "description": "the invoice total"}
    ]
}


def _pipeline(steps: list[dict], **kw) -> Pipeline:
    return Pipeline(
        id=kw.pop("id", "p1"),
        name=kw.pop("name", "eval pipeline"),
        sources=kw.pop("sources", ["docs"]),
        steps=steps,
        output_id=None,
        pipeline_type="eval",
        **kw,
    )


def _steps(**overrides) -> list[dict]:
    extract = {"op": "extract", "provider": "pdfplumber", "granularity": "page"}
    structure = {
        "op": "structure",
        "provider": overrides.pop("provider", "regex"),
        "model": overrides.pop("model", _MODEL),
        "params": overrides.pop("params", {}),
    }
    return [extract, structure]


def test_digest_is_stable_across_calls():
    p = _pipeline(_steps())
    assert config_digest(p) == config_digest(p)


def test_digest_is_a_sha256_hex():
    d = config_digest(_pipeline(_steps()))
    assert len(d) == 64 and all(c in "0123456789abcdef" for c in d)


def test_provider_change_changes_the_digest():
    a = config_digest(_pipeline(_steps(provider="regex")))
    b = config_digest(_pipeline(_steps(provider="claude")))
    assert a != b


def test_prompt_change_changes_the_digest():
    other = {
        "fields": [
            {"name": "total", "type": "number", "description": "grand total incl. tax"}
        ]
    }
    assert config_digest(_pipeline(_steps())) != config_digest(_pipeline(_steps(model=other)))


def test_params_change_changes_the_digest():
    a = config_digest(_pipeline(_steps(params={})))
    b = config_digest(_pipeline(_steps(params={"max_tokens": 400})))
    assert a != b


def test_key_order_in_params_does_not_change_the_digest():
    """Canonicalisation, not `str(dict)`. Two configs that differ only in the
    order the UI happened to serialise them are the same config, and must not
    look like drift."""
    a = config_digest(_pipeline(_steps(params={"a": 1, "b": 2})))
    b = config_digest(_pipeline(_steps(params={"b": 2, "a": 1})))
    assert a == b


def test_pipeline_identity_does_not_change_the_digest():
    """The digest identifies the *config*, not the pipeline row. Two
    pipelines with identical extract+structure steps are the same cell of a
    sweep and must compare against each other."""
    a = config_digest(_pipeline(_steps(), id="p1", name="one"))
    b = config_digest(_pipeline(_steps(), id="p2", name="two"))
    assert a == b


def test_unrelated_steps_do_not_change_the_digest():
    """A `select` or `filter` after `structure` changes what is delivered, not
    what the model was asked. Folding it in would report drift every time
    someone reorders a projection."""
    base = _steps()
    with_select = base + [{"op": "select", "fields": [{"field": "total"}]}]
    assert config_digest(_pipeline(base)) == config_digest(_pipeline(with_select))


def test_extract_provider_change_changes_the_digest():
    steps = _steps()
    steps[0] = {**steps[0], "provider": "pypdf"}
    assert config_digest(_pipeline(_steps())) != config_digest(_pipeline(steps))


def test_step_order_is_preserved_in_the_digest():
    """Two extract steps in a different order are a different pipeline."""
    a = [
        {"op": "extract", "provider": "pdfplumber", "output_field": "a"},
        {"op": "extract", "provider": "pypdf", "output_field": "b"},
        {"op": "structure", "provider": "regex", "model": _MODEL},
    ]
    b = [
        {"op": "extract", "provider": "pypdf", "output_field": "b"},
        {"op": "extract", "provider": "pdfplumber", "output_field": "a"},
        {"op": "structure", "provider": "regex", "model": _MODEL},
    ]
    assert config_digest(_pipeline(a)) != config_digest(_pipeline(b))
