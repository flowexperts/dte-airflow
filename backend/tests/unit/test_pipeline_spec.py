import pytest
from pydantic import ValidationError
from dte.models.pipeline import (
    Source, SourceCreate, Destination, DestinationCreate,
    FilterStep, RenameStep, RetypeStep,
    LookupMapStep, ExpressionMapStep,
    SortStep, AggSpec, AggregateStep,
    OutputField, JsonFileOutput, Pipeline, PipelineBase,
    JoinStep, PivotStep, SelectStep,
    CsvFileTarget, ExcelFileTarget, JsonFileTarget, ParquetS3Target,
    PostgresTarget, SqlDatabaseTarget,
    SourceTableRef, SqlDatabaseSourceConfig, coerce_source_refs,
)


def _pipeline(**overrides):
    base = dict(
        id="p1", name="test",
        sources=["s1"],
        steps=[],
        output_id="out1",
    )
    base.update(overrides)
    return Pipeline(**base)


def test_source_parses():
    s = Source(
        id="s1",
        connection_id="local_fs",
        source_type="filesystem",
        config={"bucket_url": "/tmp/data", "file_glob": "*.json"},
        table="data",
    )
    assert s.id == "s1"
    assert s.connection_id == "local_fs"
    assert s.source_type == "filesystem"
    assert s.config["bucket_url"] == "/tmp/data"
    assert s.table == "data"


def test_source_config_strict_rejects_extras():
    # `SourceCreate` carries the strict Literal + validators; `Source(table=True)`
    # is for ORM hydration and skips required-field checks at __init__.
    with pytest.raises(ValidationError):
        SourceCreate(
            id="s1", connection_id="local_fs", source_type="filesystem",
            config={"bucket_url": "/tmp", "nonsense_key": 1},
            table="t",
        )


def test_source_format_top_level():
    """`format` is a top-level Source field, not inside `config`."""
    s = SourceCreate(
        id="s_xl",
        connection_id="local_fs",
        source_type="filesystem",
        config={"bucket_url": "/tmp/data", "file_glob": "*.xlsx"},
        table="data",
        format="excel",
    )
    assert s.format == "excel"
    assert "format" not in s.config


def test_source_format_lifted_from_legacy_config():
    """Older payloads carrying `format` inside `config` migrate cleanly:
    the top-level `Source.format` picks it up and it's stripped from
    the JSONB blob."""
    s = SourceCreate(
        id="s_legacy",
        connection_id="local_fs",
        source_type="filesystem",
        config={"bucket_url": "/tmp/data", "file_glob": "*.xlsx", "format": "excel"},
        table="data",
    )
    assert s.format == "excel"
    assert "format" not in s.config


def test_source_format_glob_mismatch_rejected():
    """`format=excel` + `*.csv` glob is a footgun; reject at save-time."""
    with pytest.raises(ValidationError) as exc:
        SourceCreate(
            id="s_bad",
            connection_id="local_fs",
            source_type="filesystem",
            config={"bucket_url": "/tmp", "file_glob": "*.csv"},
            table="t",
            format="excel",
        )
    msg = str(exc.value)
    assert ".csv" in msg and "excel" in msg


def test_source_format_glob_match_ok():
    """Compatible extension aliases pass."""
    for fmt, glob in [
        ("jsonl", "*.ndjson"),
        ("csv", "*.tsv"),
        ("excel", "orders.xlsx"),
    ]:
        SourceCreate(
            id=f"s_{fmt}",
            connection_id="local_fs",
            source_type="filesystem",
            config={"bucket_url": "/tmp", "file_glob": glob},
            table="t",
            format=fmt,
        )


def test_source_format_no_glob_extension_no_check():
    """Bare directory-glob (e.g. `**/*`) is ambiguous — validator lets
    it through so the loader can decide at read time."""
    SourceCreate(
        id="s_bare",
        connection_id="local_fs",
        source_type="filesystem",
        config={"bucket_url": "/tmp", "file_glob": "**/*"},
        table="t",
        format="excel",
    )


def test_destination_json_accepts_json_and_ndjson():
    """`.json`, `.jsonl`, `.ndjson` all live in the json family — dlt
    can produce either, so all three should pass."""
    for ext in (".json", ".jsonl", ".ndjson"):
        JsonFileTarget(type="json_file", path=f"/tmp/out/orders{ext}")


def test_destination_csv_rejects_wrong_extension():
    with pytest.raises(ValidationError) as exc:
        CsvFileTarget(type="csv_file", path="/tmp/out/orders.json")
    assert ".json" in str(exc.value) and "csv_file" in str(exc.value)


def test_destination_excel_rejects_wrong_extension():
    with pytest.raises(ValidationError) as exc:
        ExcelFileTarget(type="excel_file", path="/tmp/out/orders.csv")
    assert ".csv" in str(exc.value) and "excel_file" in str(exc.value)


def test_destination_json_rejects_csv_path():
    """The prompting case: user creates `json_file` at `orders.csv` and
    gets JSON bytes in a .csv file. Reject at save-time."""
    with pytest.raises(ValidationError) as exc:
        JsonFileTarget(type="json_file", path="/tmp/out/orders.csv")
    assert ".csv" in str(exc.value) and "json_file" in str(exc.value)


def test_destination_requires_extension():
    """Missing extension is silent nonsense too — reject."""
    with pytest.raises(ValidationError) as exc:
        JsonFileTarget(type="json_file", path="/tmp/out/orders")
    assert "no file extension" in str(exc.value)


def test_destination_parquet_s3_extension_checked_on_bucket_url():
    ParquetS3Target(type="parquet_s3", bucket_url="s3://acme/out/orders.parquet")
    with pytest.raises(ValidationError) as exc:
        ParquetS3Target(type="parquet_s3", bucket_url="s3://acme/out/orders.json")
    # Field is `path` now; `bucket_url` remains accepted as an input alias.
    assert "path" in str(exc.value)


def test_destination_postgres_no_extension_check():
    """Non-file destinations have no path field — validator is a no-op."""
    PostgresTarget(type="postgres", schema="public", table="orders")
    SqlDatabaseTarget(
        type="sql_database", dialect="mysql", schema="analytics", table="orders",
    )


def test_destination_parses():
    # Use DestinationCreate (non-table) so Pydantic validators fire and
    # narrow config to the typed union.
    d = DestinationCreate(
        id="out1",
        connection_id="local_fs",
        config={"type": "json_file", "path": "/out.json"},
    )
    assert d.id == "out1"
    assert d.connection_id == "local_fs"
    assert d.config.type == "json"  # legacy "json_file" input normalises to the format-only name
    assert d.config.path == "/out.json"


def test_pipeline_holds_source_ids_and_output_id():
    p = _pipeline(sources=["s1", "s2"], output_id="dest_x")
    assert p.sources == ["s1", "s2"]
    assert p.output_id == "dest_x"


def test_invalid_source_missing_table_raises():
    with pytest.raises(ValidationError):
        SourceCreate(id="s1", connection_id="local_fs", source_type="filesystem", config={"bucket_url": "/tmp"})


def test_filter_step_in_pipeline():
    p = _pipeline(steps=[{"op": "filter", "expr": "age > 18"}])
    step = FilterStep(**p.steps[0])
    assert step.expr == "age > 18"


def test_rename_step_in_pipeline():
    p = _pipeline(steps=[{"op": "rename", "mappings": {"old_name": "new_name"}}])
    step = RenameStep(**p.steps[0])
    assert step.mappings == {"old_name": "new_name"}


def test_retype_step_in_pipeline():
    p = _pipeline(steps=[{"op": "retype", "field": "age", "to_type": "string"}])
    step = RetypeStep(**p.steps[0])
    assert step.field == "age"
    assert step.to_type == "string"


def test_lookup_map_step_in_pipeline():
    p = _pipeline(steps=[{
        "op": "map", "mode": "lookup", "field": "country_code",
        "lookup_id": "country_names",
    }])
    step = LookupMapStep(**p.steps[0])
    assert step.field == "country_code"
    assert step.lookup_id == "country_names"
    assert step.output_field is None


def test_lookup_map_step_rejects_inline_table():
    import pytest as _pt
    from pydantic import ValidationError
    with _pt.raises(ValidationError):
        LookupMapStep(
            op="map", mode="lookup", field="country_code",
            table={"US": "United States"},
        )


def test_lookup_map_step_requires_lookup_id():
    import pytest as _pt
    from pydantic import ValidationError
    with _pt.raises(ValidationError):
        LookupMapStep(op="map", mode="lookup", field="country_code")


def test_lookup_map_step_with_output_field():
    step = LookupMapStep(
        op="map", mode="lookup", field="country_code",
        lookup_id="country_names", output_field="country_name",
    )
    assert step.output_field == "country_name"


def test_expression_map_step_in_pipeline():
    p = _pipeline(steps=[{
        "op": "map", "mode": "expression",
        "output_field": "total", "expr": "price * quantity"
    }])
    step = ExpressionMapStep(**p.steps[0])
    assert step.output_field == "total"
    assert step.expr == "price * quantity"


def test_sort_step_in_pipeline():
    p = _pipeline(steps=[{"op": "sort", "by": ["age", "name"], "ascending": [True, False]}])
    step = SortStep(**p.steps[0])
    assert step.by == ["age", "name"]
    assert step.ascending == [True, False]


def test_aggregate_step_in_pipeline():
    p = _pipeline(steps=[{
        "op": "aggregate",
        "group_by": ["category"],
        "aggregations": [{"field": "amount", "func": "sum", "alias": "total"}]
    }])
    step = AggregateStep(**p.steps[0])
    assert step.group_by == ["category"]
    assert step.aggregations[0].func == "sum"


def test_destination_output_fields():
    # Use DestinationCreate (non-table) so Pydantic validators fire and
    # narrow config to the typed union.
    d = DestinationCreate(
        id="out1",
        connection_id="local_fs",
        config={
            "type": "json_file", "path": "/out.json",
            "fields": [{"field": "name", "alias": "full_name"}, {"field": "age"}]
        },
    )
    assert d.config.fields[0].alias == "full_name"
    assert d.config.fields[1].alias is None


def test_join_step_parses():
    step = JoinStep(
        op="join",
        left="users",
        right="orders",
        on="id",
        how="inner",
        output_id="joined",
    )
    assert step.left == "users"
    assert step.right == "orders"
    assert step.on == "id"
    assert step.how == "inner"
    assert step.output_id == "joined"


def test_join_step_defaults_inner():
    step = JoinStep(op="join", left="a", right="b", on="id", output_id="ab")
    assert step.how == "inner"


def test_pivot_step_parses():
    step = PivotStep(
        op="pivot",
        index="region",
        columns="product",
        values="sales",
        agg="sum",
    )
    assert step.index == "region"
    assert step.columns == "product"
    assert step.values == "sales"
    assert step.agg == "sum"


def test_pivot_step_default_agg_is_sum():
    step = PivotStep(op="pivot", index="region", columns="product", values="sales")
    assert step.agg == "sum"


def test_select_step_with_fields():
    step = SelectStep(op="select", fields=[{"field": "name"}, {"field": "age", "alias": "years"}])
    assert step.fields[1].alias == "years"
    assert step.drop == []


def test_select_step_with_drop():
    step = SelectStep(op="select", drop=["ssn", "internal_id"])
    assert step.drop == ["ssn", "internal_id"]
    assert step.fields == []


def test_select_step_fields_and_drop_mutually_exclusive():
    with pytest.raises(ValidationError):
        SelectStep(op="select", fields=[{"field": "name"}], drop=["ssn"])


def test_select_step_requires_one_of_fields_or_drop():
    with pytest.raises(ValidationError):
        SelectStep(op="select")


# ─── SourceTableRef (plan 056) ─────────────────────────────────────────────


def test_sql_database_source_config_rejects_table():
    """Which table is read moved to the pipeline's ref — the source's own
    config no longer accepts one."""
    with pytest.raises(ValidationError):
        SqlDatabaseSourceConfig(table="orders")


def test_sql_database_source_config_accepts_schema_only():
    cfg = SqlDatabaseSourceConfig(schema="analytics")
    assert cfg.schema_ == "analytics"


def test_source_table_ref_requires_alias():
    with pytest.raises(ValidationError):
        SourceTableRef(source_id="s1", alias="")


def test_source_table_ref_alias_must_be_identifier_like():
    with pytest.raises(ValidationError):
        SourceTableRef(source_id="s1", alias="not-an-identifier")
    SourceTableRef(source_id="s1", alias="an_identifier")


def test_pipeline_sources_accepts_bare_ids_as_shorthand():
    """`sources: ["s1"]` on a validated PipelineBase expands to refs with
    alias defaulted to the id."""
    p = PipelineBase(id="p1", name="test", sources=["s1"], output_id="out1")
    assert p.sources == [SourceTableRef(source_id="s1", alias="s1")]


def test_pipeline_sources_accepts_explicit_refs():
    p = PipelineBase(
        id="p1", name="test",
        sources=[{"source_id": "pgsrc", "alias": "t1", "table": "orders"}],
        output_id="out1",
    )
    assert p.sources == [SourceTableRef(source_id="pgsrc", alias="t1", table="orders")]


def test_coerce_source_refs_handles_str_dict_and_typed():
    refs = coerce_source_refs([
        "bare-id",
        {"source_id": "s2", "alias": "s2"},
        SourceTableRef(source_id="s3", alias="s3"),
    ])
    assert [r.source_id for r in refs] == ["bare-id", "s2", "s3"]
    # A hyphenated bare id (e.g. a UUID) gets a sanitized alias, not the
    # hyphenated id itself — aliases must be identifier-like.
    assert refs[0].alias == "bare_id"
