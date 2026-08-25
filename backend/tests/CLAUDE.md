## Testing tiers

Three tiers, each with a distinct purpose. Run only what the change touches.

- **Unit** (`backend/tests/unit/`) — compiler + model tests, no HTTP, no I/O. Fast. Collected by default `pytest`.
- **Integration** (`backend/tests/integration/`) — hits real Postgres via `DATABASE_URL`; auto-skips when unset. Marker: `integration`.
- **Scenarios** (`backend/tests/scenarios/`) — end-to-end user flows over the real HTTP API using `httpx.AsyncClient(ASGITransport)`. One file per step op under `steps/`, plus `test_error_paths.py`, `test_nested_fields.py`, `test_preview_endpoint.py`. Marker: `scenario`. **Excluded from the default `pytest` run** via `addopts = "--ignore=tests/scenarios"` in `pyproject.toml` — opt-in with `pytest tests/scenarios -m scenario`.

Scenario suite conventions:
- Fixtures: `client` (async), `scenario_ids` (unique id minter + reverse-dep teardown), `fixtures_dir`, `out_dir` (writes to `tmp_path`, never into the repo). See `tests/scenarios/conftest.py`.
- DSL in `tests/scenarios/helpers.py`: `create_connection`, `create_source`, `create_destination`, `create_pipeline`, `create_lookup_table`, `trigger_and_wait`, `read_output_file`.
- Deterministic hand-crafted fixtures (`orders.json`, `products.json`, `customers.json`, `nested_orders.json`, `orders_with_null.json`) — exact-match row-set assertions.
- **macOS/arm64 quirk**: sync `TestClient` spins a fresh anyio portal thread per test; successive DuckDB→Arrow-string casts segfault across threads. Fix baked into conftest: use `httpx.AsyncClient` + `ASGITransport` so everything runs on one asyncio loop.
- **JSON writer quirk**: `dte/engine/writers/json_file.py` uses `json.dumps(..., default=str)`; DuckDB `SUM(int) → DECIMAL` and `int * 1.1 → DECIMAL` land as strings. Scenario tests coerce with `float(...)`.

When adding scenario coverage: match the async fixture set, xfail (with a `reason=` pointing at the bug) if a test uncovers a real regression — do not fix compiler code inside a test PR.

