"""Unit tests for data-quality contract models and evaluator.

TDD: tests written before implementation. Run them with:
    uv run pytest tests/unit/test_quality_contracts.py -x

Covers:
- Contract model parsing / validation (plan 029 §Model)
- Pipeline.quality_contracts field round-trip
- evaluate_contracts() per contract kind
- New terminal statuses on FakeRunStore
- GET /api/runs/{id}/quality route
"""
from __future__ import annotations

import json

import pytest


# ─── Contract model tests ─────────────────────────────────────────────────────

class TestContractModels:
    def test_row_count_between_defaults(self):
        from dte.models.quality import RowCountBetween
        c = RowCountBetween(id="rc1", min=0, max=100)
        assert c.type == "row_count_between"
        assert c.severity == "fail"
        assert c.min == 0
        assert c.max == 100

    def test_column_not_null_defaults(self):
        from dte.models.quality import ColumnNotNull
        c = ColumnNotNull(id="nn1", column="amount")
        assert c.type == "column_not_null"
        assert c.severity == "fail"
        assert c.column == "amount"

    def test_column_unique_defaults(self):
        from dte.models.quality import ColumnUnique
        c = ColumnUnique(id="cu1", column="order_id")
        assert c.type == "column_unique"
        assert c.severity == "fail"

    def test_column_in_range_defaults(self):
        from dte.models.quality import ColumnInRange
        c = ColumnInRange(id="cr1", column="score", min=0.0, max=100.0)
        assert c.type == "column_in_range"
        assert c.severity == "fail"
        assert c.min == 0.0
        assert c.max == 100.0

    def test_column_in_range_partial(self):
        from dte.models.quality import ColumnInRange
        c = ColumnInRange(id="cr2", column="score", min=0.0)
        assert c.min == 0.0
        assert c.max is None

    def test_column_matches_defaults(self):
        from dte.models.quality import ColumnMatches
        c = ColumnMatches(id="cm1", column="email", regex=r".+@.+")
        assert c.type == "column_matches"
        assert c.regex == r".+@.+"

    def test_severity_warn(self):
        from dte.models.quality import RowCountBetween
        c = RowCountBetween(id="rc2", min=1, max=10, severity="warn")
        assert c.severity == "warn"

    def test_severity_invalid(self):
        from dte.models.quality import RowCountBetween
        with pytest.raises(Exception):
            RowCountBetween(id="rc3", min=1, max=10, severity="error")

    def test_contract_discriminator_round_trip(self):
        """Contract union can be parsed from a dict via the 'type' discriminator."""
        from pydantic import TypeAdapter
        from dte.models.quality import Contract

        ta = TypeAdapter(Contract)
        c = ta.validate_python({"type": "column_not_null", "id": "nn2", "column": "id"})
        from dte.models.quality import ColumnNotNull
        assert isinstance(c, ColumnNotNull)

    def test_quality_result_model(self):
        from dte.models.quality import QualityResult
        r = QualityResult(
            contract_id="rc1",
            contract_type="row_count_between",
            passed=True,
            severity="fail",
            detail="10 rows, expected 0–100",
        )
        assert r.passed is True
        assert r.detail is not None


class TestPipelineQualityContracts:
    """Pipeline.quality_contracts is an optional list of Contract."""

    def test_pipeline_without_quality_contracts(self):
        from dte.models.pipeline import PipelineBase
        p = PipelineBase(
            id="p1",
            name="Test",
            sources=["s1"],
            steps=[],
            output_id="d1",
        )
        assert p.quality_contracts == []

    def test_pipeline_with_quality_contracts(self):
        from dte.models.pipeline import PipelineBase
        p = PipelineBase(
            id="p1",
            name="Test",
            sources=["s1"],
            steps=[],
            output_id="d1",
            quality_contracts=[
                {"type": "row_count_between", "id": "rc1", "min": 1, "max": 1000},
                {"type": "column_not_null", "id": "nn1", "column": "order_id"},
            ],
        )
        assert len(p.quality_contracts) == 2
        from dte.models.quality import RowCountBetween, ColumnNotNull
        assert isinstance(p.quality_contracts[0], RowCountBetween)
        assert isinstance(p.quality_contracts[1], ColumnNotNull)

    def test_pipeline_quality_contracts_invalid_type(self):
        from dte.models.pipeline import PipelineBase
        with pytest.raises(Exception):
            PipelineBase(
                id="p1",
                name="Test",
                sources=["s1"],
                steps=[],
                output_id="d1",
                quality_contracts=[
                    {"type": "unknown_contract", "id": "x1"},
                ],
            )


# ─── Evaluator tests ──────────────────────────────────────────────────────────

@pytest.fixture
def con():
    """Shared in-memory DuckDB connection for evaluator tests."""
    import ibis
    return ibis.duckdb.connect()


@pytest.fixture
def sample_json(tmp_path):
    """Write a sample JSON file and return its path."""
    data = [
        {"order_id": 1, "amount": 10.0, "email": "a@b.com"},
        {"order_id": 2, "amount": 20.0, "email": "c@d.com"},
        {"order_id": 3, "amount": 30.0, "email": "e@f.com"},
    ]
    p = tmp_path / "orders.json"
    p.write_text(json.dumps(data))
    return str(p)


@pytest.fixture
def json_target(sample_json):
    from dte.models.pipeline import JsonFileTarget
    return JsonFileTarget(type="json_file", path=sample_json)


class TestEvaluateContracts:
    def test_row_count_between_passes(self, json_target, con):
        from dte.models.quality import RowCountBetween
        from dte.quality.evaluator import evaluate_contracts

        contracts = [RowCountBetween(id="rc1", min=1, max=10)]
        results = evaluate_contracts(contracts, json_target, con)
        assert len(results) == 1
        assert results[0].passed is True
        assert results[0].contract_id == "rc1"

    def test_row_count_between_fails_too_few(self, json_target, con):
        from dte.models.quality import RowCountBetween
        from dte.quality.evaluator import evaluate_contracts

        contracts = [RowCountBetween(id="rc1", min=100, max=1000)]
        results = evaluate_contracts(contracts, json_target, con)
        assert results[0].passed is False
        assert "3" in results[0].detail  # actual count mentioned

    def test_row_count_between_fails_too_many(self, json_target, con):
        from dte.models.quality import RowCountBetween
        from dte.quality.evaluator import evaluate_contracts

        contracts = [RowCountBetween(id="rc1", min=0, max=1)]
        results = evaluate_contracts(contracts, json_target, con)
        assert results[0].passed is False

    def test_column_not_null_passes(self, json_target, con):
        from dte.models.quality import ColumnNotNull
        from dte.quality.evaluator import evaluate_contracts

        contracts = [ColumnNotNull(id="nn1", column="order_id")]
        results = evaluate_contracts(contracts, json_target, con)
        assert results[0].passed is True

    def test_column_not_null_fails(self, tmp_path, con):
        data = [
            {"order_id": 1, "amount": 10.0},
            {"order_id": None, "amount": 20.0},  # null
        ]
        p = tmp_path / "nulls.json"
        p.write_text(json.dumps(data))
        from dte.models.pipeline import JsonFileTarget
        from dte.models.quality import ColumnNotNull
        from dte.quality.evaluator import evaluate_contracts

        target = JsonFileTarget(type="json_file", path=str(p))
        contracts = [ColumnNotNull(id="nn1", column="order_id")]
        results = evaluate_contracts(contracts, target, con)
        assert results[0].passed is False
        assert "1" in results[0].detail  # 1 null

    def test_column_unique_passes(self, json_target, con):
        from dte.models.quality import ColumnUnique
        from dte.quality.evaluator import evaluate_contracts

        contracts = [ColumnUnique(id="cu1", column="order_id")]
        results = evaluate_contracts(contracts, json_target, con)
        assert results[0].passed is True

    def test_column_unique_fails(self, tmp_path, con):
        data = [
            {"order_id": 1, "amount": 10.0},
            {"order_id": 1, "amount": 20.0},  # duplicate
        ]
        p = tmp_path / "dupes.json"
        p.write_text(json.dumps(data))
        from dte.models.pipeline import JsonFileTarget
        from dte.models.quality import ColumnUnique
        from dte.quality.evaluator import evaluate_contracts

        target = JsonFileTarget(type="json_file", path=str(p))
        contracts = [ColumnUnique(id="cu1", column="order_id")]
        results = evaluate_contracts(contracts, target, con)
        assert results[0].passed is False
        assert "1" in results[0].detail  # 1 duplicate

    def test_column_in_range_passes(self, json_target, con):
        from dte.models.quality import ColumnInRange
        from dte.quality.evaluator import evaluate_contracts

        contracts = [ColumnInRange(id="cr1", column="amount", min=0.0, max=100.0)]
        results = evaluate_contracts(contracts, json_target, con)
        assert results[0].passed is True

    def test_column_in_range_fails_below(self, tmp_path, con):
        data = [{"amount": -5.0}, {"amount": 10.0}]
        p = tmp_path / "range.json"
        p.write_text(json.dumps(data))
        from dte.models.pipeline import JsonFileTarget
        from dte.models.quality import ColumnInRange
        from dte.quality.evaluator import evaluate_contracts

        target = JsonFileTarget(type="json_file", path=str(p))
        contracts = [ColumnInRange(id="cr1", column="amount", min=0.0)]
        results = evaluate_contracts(contracts, target, con)
        assert results[0].passed is False

    def test_column_in_range_only_max(self, json_target, con):
        from dte.models.quality import ColumnInRange
        from dte.quality.evaluator import evaluate_contracts

        # amounts are 10, 20, 30 — all ≤ 50, so should pass
        contracts = [ColumnInRange(id="cr1", column="amount", max=50.0)]
        results = evaluate_contracts(contracts, json_target, con)
        assert results[0].passed is True

    def test_column_matches_passes(self, json_target, con):
        from dte.models.quality import ColumnMatches
        from dte.quality.evaluator import evaluate_contracts

        contracts = [ColumnMatches(id="cm1", column="email", regex=r".+@.+")]
        results = evaluate_contracts(contracts, json_target, con)
        assert results[0].passed is True

    def test_column_matches_fails(self, tmp_path, con):
        data = [{"email": "not-an-email"}, {"email": "ok@example.com"}]
        p = tmp_path / "emails.json"
        p.write_text(json.dumps(data))
        from dte.models.pipeline import JsonFileTarget
        from dte.models.quality import ColumnMatches
        from dte.quality.evaluator import evaluate_contracts

        target = JsonFileTarget(type="json_file", path=str(p))
        contracts = [ColumnMatches(id="cm1", column="email", regex=r".+@.+")]
        results = evaluate_contracts(contracts, target, con)
        assert results[0].passed is False

    def test_multiple_contracts(self, json_target, con):
        from dte.models.quality import RowCountBetween, ColumnNotNull
        from dte.quality.evaluator import evaluate_contracts

        contracts = [
            RowCountBetween(id="rc1", min=1, max=10),
            ColumnNotNull(id="nn1", column="order_id"),
        ]
        results = evaluate_contracts(contracts, json_target, con)
        assert len(results) == 2
        assert all(r.passed for r in results)

    def test_severity_propagated(self, json_target, con):
        from dte.models.quality import RowCountBetween
        from dte.quality.evaluator import evaluate_contracts

        contracts = [RowCountBetween(id="rc1", min=100, max=200, severity="warn")]
        results = evaluate_contracts(contracts, json_target, con)
        assert results[0].passed is False
        assert results[0].severity == "warn"

    def test_empty_contracts(self, json_target, con):
        from dte.quality.evaluator import evaluate_contracts
        results = evaluate_contracts([], json_target, con)
        assert results == []


# ─── FakeRunStore quality methods ─────────────────────────────────────────────

class TestFakeRunStoreQuality:
    @pytest.mark.asyncio
    async def test_set_and_get_quality(self):
        from tests.fakes import FakeRunStore
        from dte.models.quality import QualityResult

        store = FakeRunStore()
        run_id = await store.create("pipe1")
        results = [
            QualityResult(
                contract_id="rc1",
                contract_type="row_count_between",
                passed=True,
                severity="fail",
                detail="3 rows, expected 1–10",
            )
        ]
        await store.set_quality(run_id, results)
        fetched = await store.get_quality(run_id)
        assert len(fetched) == 1
        assert fetched[0].contract_id == "rc1"
        assert fetched[0].passed is True

    @pytest.mark.asyncio
    async def test_get_quality_missing_run(self):
        from tests.fakes import FakeRunStore
        store = FakeRunStore()
        fetched = await store.get_quality("nonexistent")
        assert fetched == []

    @pytest.mark.asyncio
    async def test_quality_summary_in_run(self):
        from tests.fakes import FakeRunStore
        from dte.models.quality import QualityResult

        store = FakeRunStore()
        run_id = await store.create("pipe1")
        results = [
            QualityResult(
                contract_id="rc1", contract_type="row_count_between",
                passed=True, severity="fail", detail="ok",
            ),
            QualityResult(
                contract_id="nn1", contract_type="column_not_null",
                passed=False, severity="fail", detail="1 null",
            ),
            QualityResult(
                contract_id="cu1", contract_type="column_unique",
                passed=False, severity="warn", detail="2 dupes",
            ),
        ]
        await store.set_quality(run_id, results)
        run = await store.get(run_id)
        assert run["quality"]["passed"] == 1
        assert run["quality"]["failed"] == 1
        assert run["quality"]["warned"] == 1


# ─── New terminal statuses ─────────────────────────────────────────────────────

class TestTerminalStatuses:
    @pytest.mark.asyncio
    async def test_completed_with_warnings_sets_finished_at(self):
        from tests.fakes import FakeRunStore
        store = FakeRunStore()
        run_id = await store.create("pipe1")
        await store.update(run_id, status="completed_with_warnings")
        run = await store.get(run_id)
        assert run["finished_at"] is not None

    @pytest.mark.asyncio
    async def test_failed_quality_sets_finished_at(self):
        from tests.fakes import FakeRunStore
        store = FakeRunStore()
        run_id = await store.create("pipe1")
        await store.update(run_id, status="failed_quality")
        run = await store.get(run_id)
        assert run["finished_at"] is not None


# ─── API route tests ───────────────────────────────────────────────────────────

@pytest.fixture
async def quality_async_client(fake_stores):
    """httpx AsyncClient over ASGITransport.

    Same pattern as scenario tests (see CLAUDE.md "Testing tiers").
    Defensively re-installs the get_current_user override — an earlier
    auth test may have popped it and the teardown ordering of async
    fixtures + sync autouse fixtures doesn't always restore it in time."""
    import httpx
    from dte.api.main import app
    from dte.api.deps import get_current_user
    from dte.models.user import Role, User
    from dte.security.permissions import ADMIN_PERMISSIONS

    def _fake_user() -> User:
        u = User(id="q-test-user", email="q@example.com", is_active=True, password_hash="unused")
        u.narrow_roles([Role(id="admin", name="admin", permissions=list(ADMIN_PERMISSIONS))])
        return u

    app.dependency_overrides[get_current_user] = lambda: _fake_user()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client, fake_stores


class TestQualityAPI:
    """Test GET /api/runs/{id}/quality route."""

    @pytest.mark.asyncio
    async def test_get_quality_not_found(self, quality_async_client):
        client, _ = quality_async_client
        r = await client.get("/api/runs/nonexistent/quality")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_get_quality_empty(self, quality_async_client):
        client, stores = quality_async_client
        run_id = await stores["run"].create("p1")
        r = await client.get(f"/api/runs/{run_id}/quality")
        assert r.status_code == 200
        assert r.json()["results"] == []
        assert r.json()["count"] == 0

    @pytest.mark.asyncio
    async def test_get_quality_with_results(self, quality_async_client):
        from dte.models.quality import QualityResult
        client, stores = quality_async_client
        run_id = await stores["run"].create("p1")
        result = QualityResult(
            contract_id="rc1", contract_type="row_count_between",
            passed=True, severity="fail", detail="3 rows",
        )
        await stores["run"].set_quality(run_id, [result])
        r = await client.get(f"/api/runs/{run_id}/quality")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 1
        assert data["results"][0]["contract_id"] == "rc1"
        assert data["results"][0]["passed"] is True

    @pytest.mark.asyncio
    async def test_get_run_includes_quality_summary(self, quality_async_client):
        from dte.models.quality import QualityResult
        client, stores = quality_async_client
        run_id = await stores["run"].create("p1")
        result = QualityResult(
            contract_id="rc1", contract_type="row_count_between",
            passed=False, severity="fail", detail="0 rows",
        )
        await stores["run"].set_quality(run_id, [result])
        r = await client.get(f"/api/runs/{run_id}")
        assert r.status_code == 200
        data = r.json()
        assert "quality" in data
        assert data["quality"]["failed"] == 1
        assert data["quality"]["passed"] == 0
