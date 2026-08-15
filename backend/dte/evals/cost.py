"""What a run cost, how much of it was cached, and how slow it was.

Plan 051's economic argument is that content-hash caching makes sweeps
affordable — parse each PDF once, re-run a cell for nothing. That argument
is unfalsifiable while the numbers are invisible, so an eval run records
its spend, its cache-hit rate, and its latency alongside its score.

Three rules, each guarding a specific way this could mislead:

**An unknown price is `None`, never a guess.** A fabricated dollar figure
is worse than a missing one: people budget against it, and it is wrong in a
direction nobody can see. Tokens are always reported because they are
measured; dollars appear only for models in the table.

**One unpriced row nulls the whole total.** A partial sum is not a smaller
bill, it is a *wrong* bill — and it errs low, which is the direction that
actually hurts. Better to say "I can't total this" than to under-report.

**Cache hits are excluded from latency.** A cache hit is not a fast model
call, it is the absence of one. Folding its 0ms into the percentiles makes
a slow provider look fast in exact proportion to how often you re-ran it,
which is precisely backwards.

Prices are USD per 1M tokens, `(input, output)`. They change; this table is
a convenience, not an invoice, and a model missing from it degrades to
`None` rather than to a wrong number.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-fable-5": (10.00, 50.00),
    # The comparison flow's headline question is whether a model is worth
    # what it costs against a cheaper one. With OpenAI unpriced, one such
    # column nulls the total for the whole comparison — correct under the
    # "never guess" rule above, and useless for the question being asked.
    "gpt-5": (1.25, 10.00),
    "gpt-5-mini": (0.25, 2.00),
    # Deterministic providers make no calls and cost nothing. Listed
    # explicitly so a regex-only run reports $0.00 rather than "unknown".
    "regex": (0.0, 0.0),
    "pdfplumber": (0.0, 0.0),
    "pypdf": (0.0, 0.0),
}

_PER_TOKEN = 1_000_000


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """USD for one model's token usage, or `None` if the model is unpriced."""
    rates = PRICES.get((model or "").strip())
    if rates is None:
        return None
    return (input_tokens * rates[0] + output_tokens * rates[1]) / _PER_TOKEN


def _percentile(values: list[int], q: float) -> int | None:
    """Nearest-rank percentile. Deliberately not interpolated: these are
    real observed call durations, and reporting one that never happened
    invites questions the number cannot answer."""
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[idx]


def _meta(row: Any) -> dict | None:
    raw = (row or {}).get("structure_meta") if isinstance(row, dict) else None
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def throughput_stats(rows: Iterable[dict]) -> dict:
    """Cost, cache-hit rate and latency for one run's materialised rows.

    Derived from `structure_meta` on the rows rather than from a separate
    accounting channel, so the numbers describe the rows that were actually
    scored — no chance of reporting a spend for work that never reached the
    scorer.
    """
    latencies: list[int] = []
    n_calls = 0
    n_meta = 0
    input_tokens = 0
    output_tokens = 0
    cost: float | None = 0.0

    for row in rows:
        meta = _meta(row)
        if meta is None:
            continue
        n_meta += 1
        if meta.get("cached"):
            continue
        n_calls += 1
        ms = meta.get("ms")
        if isinstance(ms, (int, float)):
            latencies.append(int(ms))
        in_tok = int(meta.get("input_tokens") or 0)
        out_tok = int(meta.get("output_tokens") or 0)
        input_tokens += in_tok
        output_tokens += out_tok
        if cost is not None:
            row_cost = estimate_cost(str(meta.get("model") or meta.get("provider") or ""),
                                     in_tok, out_tok)
            cost = None if row_cost is None else cost + row_cost

    if n_meta == 0:
        # No structure step ran. Zero would read as "instant and free" —
        # a claim about a model call that never happened.
        return {
            "n_calls": 0,
            "cache_hit_rate": None,
            "latency_p50_ms": None,
            "latency_p95_ms": None,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": None,
        }

    return {
        "n_calls": n_calls,
        "cache_hit_rate": (n_meta - n_calls) / n_meta,
        "latency_p50_ms": _percentile(latencies, 0.50),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost,
    }
