# Plan 085: `http_lookup` step, and a squat scan that weighs evidence

Branch: `feature/085-http-lookup` (worktree `worktrees/085-http-lookup`).

## Problem

`pypi_squat_scan` flags a package on its **name alone**: typo, lookalike or affix of a top package. A name can't tell `reqeusts` (a squat) from `requests-oauthlib` (a real project). The evidence people actually cite is per-package metadata: when it was created, whether it's still active, how many releases it has, whether it links a repo, whether it has a description, and download counts.

DTE has no step that fetches per-row data from an API. Sources load whole datasets, and the only per-row enrichment ops are `extract` and `structure`, which work on documents and text.

This is a **demo/showcase** pipeline. The aim is legible, deterministic evidence, not a production malware detector.

## Architecture change

### New step op: `http_lookup`

```jsonc
{
  "op": "http_lookup",
  "url": "https://pypi.org/pypi/{name}/json",   // {column} placeholders, URL-encoded per row
  "connection_id": null,                          // optional Airflow http conn → auth header (GitHub token)
  "fields": [                                      // JMESPath over the JSON response → typed columns
    {"name": "first_upload", "path": "min(values(releases)[][].upload_time)", "type": "timestamp"},
    {"name": "last_upload",  "path": "max(urls[].upload_time)",               "type": "timestamp"},
    {"name": "releases",     "path": "length(keys(releases))",                "type": "int"},
    {"name": "repo_url",     "path": "info.project_urls.Source || info.home_page", "type": "string"}
  ],
  "max_rows": 500,          // refuse to fan out over more rows than this
  "on_error": "null"        // "null" (default) | "fail"
}
```

- **Built like `structure`**: it goes through `engine.apply_enrichment` with `EnrichmentSpec` (`dte/engine/base.py`) and adds a `<name>_meta` JSON column (status, cached, error, ms), the same way `structure_meta` does.
- **Cache**: `derived_key(sha256(url), "http_lookup", {"day": utc_date})` in the artifact store. Each URL is fetched at most once per day, so editor previews and re-runs that day are free. Failed requests are **not cached** (the same rule `_apply_structure` follows). A 404 is a *result*: the fields come back null and the meta says `status: 404`. A package deleted from PyPI is evidence in its own right.
- **`max_rows` guard** raises a `CompilerError` before any request goes out. It forces the narrow-first pattern: this op must never fan out over 700k rows, in a run or in a preview.
- **JMESPath** (`jmespath`, already installed in the image through Airflow's own dependencies). It's declared in `pyproject.toml` without a version, so Airflow's constraints pick the version. It's tested on live PyPI and pypistats responses: every expression above works.
- HTTP via `httpx` (already a dependency), with a 10 s timeout and sequential requests. A demo funnel produces dozens of rows a day, and if that grows the ceiling is noted in a `ponytail:` comment.

### `pypi_squat_scan` gains evidence

After step 8, where `target` is set:

1. `http_lookup` against `pypi.org/pypi/{name}/json`: `first_upload`, `last_upload`, `releases`, `repo_url`, `summary`, `author_email`.
2. `http_lookup` against `pypistats.org/api/packages/{name}/recent`: `downloads_month`.
3. `map` → `risk`: a points-based `CASE`. Age under 14 days, a single release, no repo, an empty summary, and downloads under 1% of the target's each score +1, and the `lookalike` rule scores +1. Plus `risk_reasons` as a readable string.
4. `select` now outputs `name, rule, target, risk, risk_reasons, first_upload, last_upload, releases, repo_url, downloads_month, scanned_on`, sorted by risk descending.

The step-3 weights are a demo heuristic and are documented as one.

## Tasks

| # | Task | Files |
|---|---|---|
| 1 | `HttpLookupStep` model and registration in the step map; validation (placeholders must be identifiers, JMESPath must compile, `params` must not carry secrets) | `dte/models/pipeline.py`, `tests/unit/test_http_lookup_model.py` |
| 2 | `_apply_http_lookup`: URL templating, the max_rows guard, the daily cache, the 404-as-result rule, typed columns plus `_meta`, Airflow http connection auth | `dte/compiler/ibis_compiler.py`, `tests/unit/test_http_lookup.py` (local `ThreadingHTTPServer`, like `test_loader_sample.py` in 084) |
| 3 | Builder editor: URL input, a field rows editor (name / path / type), max_rows | `frontend/src/components/builder/steps/editors.tsx` + step registry |
| 4 | Update `pypi_squat_scan` with the steps above; check a preview and a run on the stack | stack data (seed script if one exists for the demo) |
| 5 | Docs: a backend `CLAUDE.md` section, the step list in user docs | `backend/CLAUDE.md`, `docs/user/...` |

## Non-goals

- **Source-code analysis.** It needs sdists downloaded and unpacked, which doesn't fit an HTTP step. The follow-up plan treats sdists as `documents`, then runs `extract`, then `structure` with the `regex` provider to flag `exec`/`base64`/`subprocess`/network calls in `setup.py`, with an optional `claude` verdict. That reuses DTE's unstructured path.
- POST requests, pagination inside a lookup, and concurrency or rate limiting beyond sequential calls.
- GitHub stars or last push. Possible with the same op plus a `connection_id`, but left out of the demo's first cut.

## Verification

- Unit tests (written first): templating with URL-encoding, every field type, a 404 producing nulls with `status` in meta, a 500 that isn't cached and a 200 that is, a repeat call the same day making 0 requests, the max_rows guard firing before any request, and `on_error="fail"`.
- `uv run pytest tests/unit` and the scenario suite.
- Stack: preview `pypi_squat_scan` and confirm the evidence columns are populated. Trigger a run and check the `pypi_squat_alerts` rows sort by risk. A second preview should make 0 outbound requests (`_meta.cached = true`).
