"""Automap: propose a source-column → destination-column mapping.

Two passes that cost nothing, then one that costs money:

1. **exact** on the normalised name — `customer_id` == `CustomerID`.
2. **fuzzy** via `difflib` — `ship_date` ≈ `shipping_date`. stdlib, no
   dependency, deterministic, runs in CI.
3. **llm** over whatever is left, only when a key is present. Semantic
   renames (`dob` → `birth_date`) are the whole reason this pass exists;
   nothing else here can see them.

A type-family mismatch never rejects a match — it caps confidence and
attaches a warning. Rejecting would hide the exact-name pairs people most
want to review, and the user is the one accepting rows anyway.
"""

from __future__ import annotations

import difflib
import json
import os
import re
from dataclasses import dataclass
from dataclasses import field as dc_field

FUZZY_CUTOFF = 0.8
LLM_CONFIDENCE = 0.6          # the API exposes no per-field confidence
MISMATCH_CAP = 0.5

DEFAULT_MODEL = "claude-opus-5"


@dataclass
class Field:
    name: str
    type: str = ""


@dataclass
class Match:
    dest: str
    source: str | None = None
    confidence: float = 0.0
    via: str | None = None            # "exact" | "fuzzy" | "llm" | None
    warning: str | None = None


@dataclass
class AutomapResult:
    matches: list[Match] = dc_field(default_factory=list)
    unmatched_source: list[str] = dc_field(default_factory=list)
    llm_error: str | None = None


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


_FAMILIES = (
    ("num", ("int", "float", "decimal", "numeric", "double")),
    ("time", ("date", "time", "timestamp")),
    ("bool", ("bool",)),
    ("str", ("string", "str", "char", "text", "uuid", "json")),
)


def _family(dtype: str) -> str:
    d = (dtype or "").lower()
    for name, needles in _FAMILIES:
        if any(n in d for n in needles):
            return name
    return "other"


def _warn(src: Field, dst: Field) -> str | None:
    a, b = _family(src.type), _family(dst.type)
    if not src.type or not dst.type or a == "other" or b == "other":
        return None
    if a != b:
        return f"{src.type} → {dst.type}"
    return None


def _finish(src: Field, dst: Field, confidence: float, via: str) -> Match:
    warning = _warn(src, dst)
    return Match(
        dest=dst.name,
        source=src.name,
        confidence=min(confidence, MISMATCH_CAP) if warning else confidence,
        via=via,
        warning=warning,
    )


def automap(
    source_fields: list[Field],
    dest_fields: list[Field],
    use_llm: bool = True,
) -> AutomapResult:
    by_dest: dict[str, Match] = {d.name: Match(dest=d.name) for d in dest_fields}
    src_left = {f.name: f for f in source_fields}
    dst_left = {f.name: f for f in dest_fields if f.name in by_dest}

    # Pass 1 — exact on the normalised name.
    src_by_norm: dict[str, Field] = {}
    for f in source_fields:
        src_by_norm.setdefault(_norm(f.name), f)
    for dst in list(dst_left.values()):
        src = src_by_norm.get(_norm(dst.name))
        if src and src.name in src_left:
            by_dest[dst.name] = _finish(src, dst, 1.0, "exact")
            del src_left[src.name], dst_left[dst.name]

    # Pass 2 — fuzzy, greedy best-first so the strongest pair claims its
    # column before a weaker one can take it.
    scored = sorted(
        (
            (difflib.SequenceMatcher(None, _norm(s.name), _norm(d.name)).ratio(), s, d)
            for s in src_left.values()
            for d in dst_left.values()
        ),
        key=lambda t: (-t[0], t[1].name, t[2].name),
    )
    for ratio, src, dst in scored:
        if ratio < FUZZY_CUTOFF:
            break
        if src.name in src_left and dst.name in dst_left:
            by_dest[dst.name] = _finish(src, dst, round(ratio, 3), "fuzzy")
            del src_left[src.name], dst_left[dst.name]

    result = AutomapResult(
        matches=[by_dest[d.name] for d in dest_fields],
        unmatched_source=sorted(src_left),
    )
    if not (use_llm and dst_left and src_left):
        return result

    try:
        guessed = _llm_match(list(src_left.values()), list(dst_left.values()))
    except Exception as e:  # noqa: BLE001 — a failed guess is not a failed request
        result.llm_error = f"{type(e).__name__}: {e}"
        return result

    for dest_name, source_name in guessed.items():
        # A model must not invent a column, and must not steal one the
        # heuristic already claimed.
        if dest_name in dst_left and source_name in src_left:
            by_dest[dest_name] = _finish(
                src_left[source_name], dst_left[dest_name], LLM_CONFIDENCE, "llm"
            )
            del src_left[source_name], dst_left[dest_name]

    result.matches = [by_dest[d.name] for d in dest_fields]
    result.unmatched_source = sorted(src_left)
    return result


_PROMPT = """\
Map destination columns to source columns for a data pipeline.

Source columns:
{source}

Destination columns:
{dest}

Rules:
- Match on meaning, not spelling — the obvious spelling matches are already done.
- Use each source column at most once.
- Return null for a destination column with no plausible source. A null is
  correct; a wrong mapping silently corrupts a column.
- Use only the names given above verbatim.
"""


def _llm_match(sources: list[Field], dests: list[Field]) -> dict[str, str | None]:
    """One Claude call over the leftovers. Raises on anything at all — the
    caller turns that into `llm_error` and keeps the heuristic result."""
    from dte.airflow import connections  # the `anthropic_default` connection

    schema = {
        "type": "object",
        "properties": {
            d.name: {"type": ["string", "null"]} for d in dests
        },
        "required": [d.name for d in dests],
        "additionalProperties": False,
    }
    prompt = _PROMPT.format(
        source="\n".join(f"- {f.name} ({f.type})" for f in sources),
        dest="\n".join(f"- {f.name} ({f.type})" for f in dests),
    )
    client = connections.model_client("claude", None)
    response = client.messages.create(
        model=os.environ.get("DTE_AUTOMAP_MODEL", DEFAULT_MODEL),
        max_tokens=2048,
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": prompt}],
    )
    text = next((b.text for b in response.content if b.type == "text"), "")
    return json.loads(text or "{}")
