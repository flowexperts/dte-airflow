"""Extract inline `table` dicts from map/lookup steps into first-class
`LookupTable` rows.

Legacy step shape:
    {"op": "map", "mode": "lookup", "field": "cc",
     "table": {"US": "United States"}, "default": "Unknown"}

New step shape:
    {"op": "map", "mode": "lookup", "field": "cc",
     "lookup_id": "lookup_<sha1[:12]>"}

Identical `(mappings, default)` blobs across pipelines dedupe to one row.
Idempotent — steps already in the new shape pass through untouched.

Usage:
    cd backend
    uv run python scripts/migrate_extract_lookups.py           # dry run
    uv run python scripts/migrate_extract_lookups.py --write   # persist
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json


def _dedupe_id(mappings: dict, default: str | None) -> str:
    blob = json.dumps(
        {"mappings": mappings, "default": default}, sort_keys=True, default=str
    )
    digest = hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]
    return f"lookup_{digest}"


async def _upsert_lookup(
    lt_store,
    lookup_id: str,
    mappings: dict,
    default: str | None,
    log: list[str],
) -> None:
    from dte.models.pipeline import LookupTableCreate
    if await lt_store.get(lookup_id):
        return
    await lt_store.save(LookupTableCreate(
        id=lookup_id,
        name=None,
        mappings=mappings,
        default=default,
    ))
    log.append(f"  created lookup_table {lookup_id} ({len(mappings)} entries)")


async def _migrate_pipeline(pipeline, lt_store, log: list[str]) -> tuple[list[dict], bool]:
    steps = copy.deepcopy(pipeline.steps or [])
    changed = False
    for step in steps:
        if step.get("op") != "map" or step.get("mode") != "lookup":
            continue
        if "lookup_id" in step and step["lookup_id"]:
            continue  # already migrated
        mappings = step.pop("table", None) or {}
        default = step.pop("default", None)
        if not mappings:
            continue
        lookup_id = _dedupe_id(mappings, default)
        await _upsert_lookup(lt_store, lookup_id, mappings, default, log)
        step["lookup_id"] = lookup_id
        changed = True
    return steps, changed


async def main(write: bool) -> None:
    from dte.api.deps import get_lookup_table_store, get_pipeline_store
    from dte.models.pipeline import Pipeline
    p_store = get_pipeline_store()
    lt_store = get_lookup_table_store()

    total = 0
    changed_count = 0
    for pipeline in await p_store.list(limit=10_000):
        total += 1
        log: list[str] = []
        new_steps, changed = await _migrate_pipeline(pipeline, lt_store, log)
        if not changed:
            continue
        changed_count += 1
        print(f"[pipeline {pipeline.id}] rewrote lookup steps")
        for line in log:
            print(line)
        if write:
            updated = Pipeline(
                id=pipeline.id,
                name=pipeline.name,
                sources=pipeline.sources,
                steps=new_steps,
                output_id=pipeline.output_id,
            )
            await p_store.save(updated)

    suffix = " — saved" if write else " (dry run; pass --write to persist)"
    print(f"\n{changed_count}/{total} pipelines changed{suffix}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="Persist changes")
    args = ap.parse_args()
    asyncio.run(main(write=args.write))
