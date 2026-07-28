"""Unit tests for the engine × connection-type capability matrix and the
validator that turns mismatches into structured 422 payloads."""
from __future__ import annotations

import pytest

from dte.models.pipeline import (
    EngineIncompatible,
    resolve_pipeline_engine,
    validate_pipeline_engine_compat,
)


class TestResolveEngine:
    def test_explicit_choice_returned_verbatim(self):
        assert resolve_pipeline_engine("postgres", ["postgres"]) == "postgres"
        assert resolve_pipeline_engine("trino", ["snowflake", "postgres"]) == "trino"
        assert resolve_pipeline_engine("duckdb", ["local_fs"]) == "duckdb"

    def test_auto_all_duckdb_native_returns_duckdb(self):
        assert resolve_pipeline_engine("auto", ["local_fs"]) == "duckdb"
        assert resolve_pipeline_engine("auto", ["local_fs", "s3", "mongodb"]) == "duckdb"

    def test_auto_single_postgres_returns_postgres_pushdown(self):
        assert resolve_pipeline_engine("auto", ["postgres"]) == "postgres"

    def test_auto_single_bigquery_returns_bigquery_pushdown(self):
        assert resolve_pipeline_engine("auto", ["bigquery"]) == "bigquery"

    def test_auto_two_postgres_same_type_returns_postgres(self):
        # Multiple sources of the same non-DuckDB dialect → pushdown to that engine.
        assert resolve_pipeline_engine("auto", ["postgres", "postgres"]) == "postgres"

    def test_auto_mixed_falls_back_to_duckdb(self):
        # Mixed postgres + filesystem: duckdb is the only common denominator we
        # can federate through (via attach), so return duckdb.  If duckdb can't
        # actually read postgres in the current architecture,
        # validate_pipeline_engine_compat catches it.
        assert resolve_pipeline_engine("auto", ["postgres", "local_fs"]) == "duckdb"

    def test_auto_no_sources_returns_duckdb(self):
        assert resolve_pipeline_engine("auto", []) == "duckdb"

    def test_empty_string_treated_as_auto(self):
        assert resolve_pipeline_engine("", ["postgres"]) == "postgres"


class TestValidateEngineCompat:
    def test_duckdb_accepts_filesystem_source_and_local_dest(self):
        # No exception.
        validate_pipeline_engine_compat(
            engine="duckdb",
            sources=[("s1", "local_fs")],
            destination=("d1", "local_fs"),
        )

    def test_duckdb_rejects_bigquery_source_with_structured_payload(self):
        with pytest.raises(EngineIncompatible) as ei:
            validate_pipeline_engine_compat(
                engine="duckdb",
                sources=[("bq_orders", "bigquery")],
                destination=("d1", "local_fs"),
            )
        payload = ei.value.payload()
        assert payload["code"] == "engine_incompatible"
        assert payload["engine"] == "duckdb"
        assert len(payload["incompatible_sources"]) == 1
        assert payload["incompatible_sources"][0]["source_id"] == "bq_orders"
        assert payload["incompatible_sources"][0]["connection_type"] == "bigquery"
        assert payload["incompatible_destination"] is None

    def test_postgres_engine_accepts_postgres_source_only(self):
        validate_pipeline_engine_compat(
            engine="postgres",
            sources=[("pg_users", "postgres")],
            destination=("d1", "postgres"),
        )
        with pytest.raises(EngineIncompatible):
            validate_pipeline_engine_compat(
                engine="postgres",
                sources=[("pg_users", "postgres"), ("fs", "local_fs")],
                destination=("d1", "postgres"),
            )

    def test_reports_incompatible_destination_when_dialect_missing(self):
        # DuckDB engine has no bigquery writer today.
        with pytest.raises(EngineIncompatible) as ei:
            validate_pipeline_engine_compat(
                engine="duckdb",
                sources=[("fs", "local_fs")],
                destination=("bq_out", "bigquery"),
            )
        payload = ei.value.payload()
        assert payload["incompatible_destination"]["destination_id"] == "bq_out"
        assert payload["incompatible_destination"]["connection_type"] == "bigquery"

    def test_trino_can_federate_snowflake_and_bigquery(self):
        # No exception — trino is the "everything" engine when enabled.
        validate_pipeline_engine_compat(
            engine="trino",
            sources=[("sf", "snowflake"), ("bq", "bigquery")],
            destination=("d1", "postgres"),
        )
