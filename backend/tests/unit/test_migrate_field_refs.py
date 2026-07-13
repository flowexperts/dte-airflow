import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from migrate_field_refs import _norm, _rewrite_step, _rewrite_output


def test_norm_rewrites_double_underscore():
    assert _norm("order__amount") == "order.amount"
    assert _norm("user__address__city") == "user.address.city"


def test_norm_is_idempotent_on_dot_form():
    assert _norm("order.amount") == "order.amount"


def test_norm_preserves_reserved_dlt_names():
    assert _norm("_dlt_id") == "_dlt_id"
    assert _norm("_dlt_load_id") == "_dlt_load_id"


def test_rewrite_select_step_fields():
    step = {
        "op": "select",
        "fields": [
            {"field": "id"},
            {"field": "order__amount", "alias": "amount"},
            {"field": "_dlt_id"},
        ],
    }
    out = _rewrite_step(step)
    assert out["fields"][1]["field"] == "order.amount"
    assert out["fields"][1]["alias"] == "amount"
    assert out["fields"][2]["field"] == "_dlt_id"


def test_rewrite_aggregate_step():
    step = {
        "op": "aggregate",
        "group_by": ["region__code"],
        "aggregations": [{"field": "order__amount", "func": "sum", "alias": "gmv"}],
    }
    out = _rewrite_step(step)
    assert out["group_by"] == ["region.code"]
    assert out["aggregations"][0]["field"] == "order.amount"


def test_rewrite_rename_mappings_keys():
    step = {"op": "rename", "mappings": {"user__id": "customer_id"}}
    out = _rewrite_step(step)
    assert out["mappings"] == {"user.id": "customer_id"}


def test_rewrite_output_fields():
    out = _rewrite_output({
        "type": "json_file",
        "path": "/tmp/o.json",
        "fields": [{"field": "order__amount", "alias": "amt"}],
    })
    assert out["fields"][0]["field"] == "order.amount"
