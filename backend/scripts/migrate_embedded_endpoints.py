"""Migrate legacy pipelines with embedded sources / outputs into the new
first-class source and destination tables.

For each pipeline:
- Every embedded `Source` in `sources` is upserted into the sources store
  with its current id. Id collision with a different config gets a
  suffix (`-2`, `-3`, …) and is logged.
- The embedded `output` is upserted into the destinations store with a
  generated id `<pipeline_id>_output` (falling back to `-2`, … on
  collision).
- `pipeline.sources` becomes a list of ids; `pipeline.output` becomes
  `pipeline.output_id`.

Idempotent: pipelines that already use id refs pass through untouched.

Usage:
    cd backend
    uv run python scripts/migrate_embedded_endpoints.py           # dry run
    uv run python scripts/migrate_embedded_endpoints.py --write   # persist

Picks the active stores off `DTE_DATABASE_URL` — same rule as `dte.api.deps`.
"""
from __future__ import annotations

import argparse
import asyncio
import copy


def _is_embedded_source(entry) -> bool:
    return isinstance(entry, dict) and "source_type" in entry


def _is_embedded_output(entry) -> bool:
    return isinstance(entry, dict) and "type" in entry


def _as_dict(row) -> dict:
    """Convert a store row to a plain dict for comparison.

    Typed store rows (Source, Destination) have `to_api_dict()` / attribute
    access; legacy dict rows pass through unchanged."""
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    if hasattr(row, "to_api_dict"):
        return row.to_api_dict()
    # Source / Connection: fall back to model_dump
    return row.model_dump()


async def _upsert_with_id_collision(store, entry: dict, base_id: str, log: list[str]) -> str:
    """Insert `entry` into `store` under `base_id`, appending `-N` on
    collision if the existing row has a different payload. Returns the id
    that was ultimately used."""
    existing = await store.get(base_id)
    if existing is None:
        entry = {**entry, "id": base_id}
        await store.save(entry)
        return base_id
    # Same id — if same payload, no-op; else pick suffix.
    if _as_dict(existing) == {**entry, "id": base_id}:
        return base_id
    suffix = 2
    while True:
        candidate = f"{base_id}-{suffix}"
        collision = await store.get(candidate)
        if collision is None:
            log.append(f"  id collision on '{base_id}' → stored as '{candidate}'")
            entry = {**entry, "id": candidate}
            await store.save(entry)
            return candidate
        if _as_dict(collision) == {**entry, "id": candidate}:
            return candidate
        suffix += 1


async def _migrate_pipeline(pipeline: dict, s_store, d_store, log: list[str]) -> tuple[dict, bool]:
    """Return (new_pipeline_dict, changed)."""
    updated = copy.deepcopy(pipeline)
    changed = False

    # Sources: list may contain embedded dicts (old shape) or id strs (new).
    new_source_ids: list[str] = []
    for entry in updated.get("sources", []):
        if isinstance(entry, str):
            new_source_ids.append(entry)
            continue
        if _is_embedded_source(entry):
            sid = entry["id"]
            used_id = await _upsert_with_id_collision(s_store, entry, sid, log)
            new_source_ids.append(used_id)
            changed = True
        else:
            raise ValueError(f"unrecognised source entry in pipeline '{pipeline['id']}': {entry!r}")
    updated["sources"] = new_source_ids

    # Output: embedded dict → destination row; already-id becomes `output_id`.
    output = updated.pop("output", None)
    if "output_id" in updated:
        pass  # already migrated
    elif output is not None and _is_embedded_output(output):
        base = f"{pipeline['id']}_output"
        dest_row = {"id": base, "config": output}
        used_id = await _upsert_with_id_collision(d_store, dest_row, base, log)
        updated["output_id"] = used_id
        changed = True
    else:
        raise ValueError(f"pipeline '{pipeline['id']}' has no output and no output_id")

    return updated, changed


async def main(write: bool) -> None:
    from dte.api.deps import (
        get_destination_store,
        get_pipeline_store,
        get_source_store,
    )
    p_store = get_pipeline_store()
    s_store = get_source_store()
    d_store = get_destination_store()

    pipelines = await p_store.list(limit=10_000)
    total = 0
    changed = 0
    for p in pipelines:
        total += 1
        log: list[str] = []
        new_p, was_changed = await _migrate_pipeline(p, s_store, d_store, log)
        if not was_changed:
            continue
        changed += 1
        print(f"[{p['id']}] migrated → sources={new_p['sources']} output_id={new_p['output_id']}")
        for line in log:
            print(line)
        if write:
            await p_store.save(new_p)
    suffix = " — saved" if write else " (dry run; pass --write to persist)"
    print(f"\n{changed}/{total} pipelines changed{suffix}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="Persist changes")
    args = ap.parse_args()
    asyncio.run(main(write=args.write))
