"""Deterministic structured diff between two pipeline configs.

Steps are diffed positionally by index — a change at index 3 shows both
before + after; an insertion or deletion shows only one side. Whole-step
comparison (no per-key diff inside a step) is deliberate: steps are
small dicts and side-by-side reading is clearer than field-level noise.

Output is JSON-serialisable so the API can return it directly.
"""
from __future__ import annotations

from typing import Any, TypedDict


class StepChange(TypedDict, total=False):
    index: int
    kind: str  # "added" | "removed" | "changed"
    op: str
    before: dict | None
    after: dict | None


class PipelineDiff(TypedDict):
    name_changed: bool
    name_before: str | None
    name_after: str | None
    sources_added: list[str]
    sources_removed: list[str]
    output_id_changed: bool
    output_id_before: str | None
    output_id_after: str | None
    steps: list[StepChange]


def diff_pipeline(before: dict[str, Any], after: dict[str, Any]) -> PipelineDiff:
    """Compare two `PipelineBase.model_dump()` dicts.

    Positional step diff: each index yields one entry — added / removed /
    changed / (unchanged rows are omitted). Order-only reshuffles surface
    as `changed` at each moved position, which is the correct signal for
    users: pipeline semantics depend on step order.
    """
    b_steps: list[dict] = list(before.get("steps") or [])
    a_steps: list[dict] = list(after.get("steps") or [])
    n = max(len(b_steps), len(a_steps))
    steps: list[StepChange] = []
    for i in range(n):
        b = b_steps[i] if i < len(b_steps) else None
        a = a_steps[i] if i < len(a_steps) else None
        if b is None and a is not None:
            steps.append({"index": i, "kind": "added", "op": a.get("op", ""), "before": None, "after": a})
        elif a is None and b is not None:
            steps.append({"index": i, "kind": "removed", "op": b.get("op", ""), "before": b, "after": None})
        elif b != a:
            steps.append({
                "index": i,
                "kind": "changed",
                "op": (a or {}).get("op") or (b or {}).get("op") or "",
                "before": b,
                "after": a,
            })

    b_sources = set(before.get("sources") or [])
    a_sources = set(after.get("sources") or [])
    sources_added = sorted(a_sources - b_sources)
    sources_removed = sorted(b_sources - a_sources)

    name_before = before.get("name")
    name_after = after.get("name")
    output_before = before.get("output_id")
    output_after = after.get("output_id")

    return {
        "name_changed": name_before != name_after,
        "name_before": name_before,
        "name_after": name_after,
        "sources_added": sources_added,
        "sources_removed": sources_removed,
        "output_id_changed": output_before != output_after,
        "output_id_before": output_before,
        "output_id_after": output_after,
        "steps": steps,
    }


def summarise_diff(d: PipelineDiff) -> str:
    """One-line human summary suitable for the `summary` column."""
    parts: list[str] = []
    if d["name_changed"]:
        parts.append(f"name: {d['name_before']!r} → {d['name_after']!r}")
    added = [s for s in d["steps"] if s["kind"] == "added"]
    removed = [s for s in d["steps"] if s["kind"] == "removed"]
    changed = [s for s in d["steps"] if s["kind"] == "changed"]
    step_bits = []
    if added:
        step_bits.append("+" + ", +".join(s["op"] for s in added))
    if removed:
        step_bits.append("-" + ", -".join(s["op"] for s in removed))
    if changed:
        step_bits.append("~" + ", ~".join(s["op"] for s in changed))
    if step_bits:
        parts.append("steps: " + " ".join(step_bits))
    if d["sources_added"] or d["sources_removed"]:
        chunks = []
        if d["sources_added"]:
            chunks.append("+" + ",".join(d["sources_added"]))
        if d["sources_removed"]:
            chunks.append("-" + ",".join(d["sources_removed"]))
        parts.append("sources: " + " ".join(chunks))
    if d["output_id_changed"]:
        parts.append(f"output: {d['output_id_before']} → {d['output_id_after']}")
    return "; ".join(parts) if parts else "no changes"
