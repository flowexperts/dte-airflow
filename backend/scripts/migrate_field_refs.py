"""Rewrite field references in every stored pipeline from `parent__child`
to `parent.child` (dot form).

Idempotent: refs already containing dots pass through untouched; refs
starting with `_dlt_` (reserved names) are preserved as-is.

Usage:
    cd backend
    uv run python scripts/migrate_field_refs.py           # dry run
    uv run python scripts/migrate_field_refs.py --write   # actually save

Picks the active store off `DATABASE_URL` — same rule as `dte.api.deps`.
"""
from __future__ import annotations

import argparse
import asyncio
import copy


def _norm(ref: str) -> str:
    if ref.startswith("_dlt_"):
        return ref
    if "." in ref:
        return ref
    return ref.replace("__", ".")


def _rewrite_step(step: dict) -> dict:
    step = copy.deepcopy(step)
    op = step.get("op")

    if "field" in step and isinstance(step["field"], str):
        step["field"] = _norm(step["field"])
    if "output_field" in step and isinstance(step["output_field"], str):
        step["output_field"] = _norm(step["output_field"])
    if "on" in step:
        on = step["on"]
        if isinstance(on, str):
            step["on"] = _norm(on)
        elif isinstance(on, list):
            step["on"] = [_norm(x) for x in on]
    for key in ("by", "group_by", "drop"):
        if key in step and isinstance(step[key], list):
            step[key] = [_norm(x) for x in step[key]]
    if op == "aggregate" and isinstance(step.get("aggregations"), list):
        step["aggregations"] = [
            {**a, "field": _norm(a["field"])}
            for a in step["aggregations"]
        ]
    if op == "select" and isinstance(step.get("fields"), list):
        step["fields"] = [
            {**f, "field": _norm(f["field"])}
            for f in step["fields"]
        ]
    if op == "rename" and isinstance(step.get("mappings"), dict):
        step["mappings"] = {
            _norm(k): v for k, v in step["mappings"].items()
        }
    if op == "pivot":
        for k in ("index", "columns", "values"):
            v = step.get(k)
            if isinstance(v, str):
                step[k] = _norm(v)
            elif isinstance(v, list):
                step[k] = [_norm(x) for x in v]
    return step


def _rewrite_output(output: dict | None) -> dict | None:
    if not output or not isinstance(output.get("fields"), list):
        return output
    output = copy.deepcopy(output)
    output["fields"] = [
        {**f, "field": _norm(f["field"])} for f in output["fields"]
    ]
    return output


def _rewrite_pipeline(p) -> tuple[object, bool]:
    """Return (updated_model, changed_bool). Uses model_copy so we return
    the same Pydantic type the store expects."""
    data = p.model_dump() if hasattr(p, "model_dump") else dict(p)
    before = copy.deepcopy(data)
    data["steps"] = [_rewrite_step(s) for s in data.get("steps", [])]
    data["output"] = _rewrite_output(data.get("output"))
    changed = data != before
    if not changed:
        return p, False
    from dte.models.pipeline import Pipeline
    return Pipeline(**data), True


async def main(write: bool) -> None:
    from dte.api.deps import get_pipeline_store
    store = get_pipeline_store()
    pipelines = await store.list()
    total = 0
    changed = 0
    for p in pipelines:
        total += 1
        new_p, was_changed = _rewrite_pipeline(p)
        if not was_changed:
            continue
        changed += 1
        print(f"[{p.id}] would rewrite")
        if write:
            await store.update(p.id, new_p)
    print(f"\n{changed}/{total} pipelines would change" + (
        " — saved" if write else " (dry run; pass --write to save)"
    ))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="Persist changes")
    args = ap.parse_args()
    asyncio.run(main(write=args.write))
