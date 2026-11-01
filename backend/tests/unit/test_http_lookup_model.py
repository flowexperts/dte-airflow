"""`HttpLookupStep` validation (plan 085)."""
import pytest
from pydantic import ValidationError

from dte.models.pipeline import HttpLookupStep, Pipeline, parse_step


def _step(**over):
    step = {
        "op": "http_lookup",
        "url": "https://pypi.org/pypi/{name}/json",
        "fields": [{"name": "releases", "path": "length(keys(releases))", "type": "int"}],
    }
    step.update(over)
    return step


def test_defaults_and_registration():
    s = HttpLookupStep(**_step())
    assert s.max_rows == 500
    assert s.on_error == "null"
    assert s.connection_id is None
    assert s.fields[0].type == "int"
    assert isinstance(parse_step(_step()), HttpLookupStep)


def test_pipeline_accepts_the_step():
    Pipeline(id="p", name="p", sources=["s"], output_id="o", steps=[_step()])


@pytest.mark.parametrize("url", [
    "https://x/{bad name}/json",
    "https://x/{1st}/json",
    "https://x/{}/json",
])
def test_placeholders_must_be_identifiers(url):
    with pytest.raises(ValidationError, match="placeholder"):
        HttpLookupStep(**_step(url=url))


def test_url_must_be_http():
    with pytest.raises(ValidationError, match="http"):
        HttpLookupStep(**_step(url="file:///etc/{name}"))


def test_jmespath_must_compile():
    with pytest.raises(ValidationError, match="JMESPath"):
        HttpLookupStep(**_step(fields=[{"name": "x", "path": "info..x"}]))


def test_field_names_unique_and_identifiers():
    with pytest.raises(ValidationError, match="duplicate"):
        HttpLookupStep(**_step(fields=[{"name": "a", "path": "a"}, {"name": "a", "path": "b"}]))
    with pytest.raises(ValidationError, match="identifier"):
        HttpLookupStep(**_step(fields=[{"name": "bad name", "path": "a"}]))


def test_needs_at_least_one_field():
    with pytest.raises(ValidationError, match="field"):
        HttpLookupStep(**_step(fields=[]))
