# dte-sdk

Batch data transformation SDK. Define sources, destinations, lookup tables, and pipelines as Python objects; compile them with ibis; execute them with DuckDB.

Designed to be embedded in orchestration tools (Airflow, Prefect, Dagster) — a pipeline is a plain Python value you can hand to an operator.

## Install

```bash
pip install dte-sdk                   # core
pip install "dte-sdk[all]"            # + parquet, s3, mongodb, fernet
```

## Usage (sketch — full example in `examples/`)

```python
from dte_sdk import SourceBase, DestinationBase, PipelineBase, DuckDBEngine, load_source, compile_pipeline

source = SourceBase(id="orders", source_type="filesystem", config={"bucket_url": "./data/orders/", "file_glob": "*.json"})
dest = DestinationBase(id="out", config={"type": "json_file", "path": "./out.json"})
pipeline = PipelineBase(id="p", sources=["orders"], output_id="out", steps=[])

engine = DuckDBEngine()
tables = {source.id: load_source(source, engine.con, credentials={})}
compiled = compile_pipeline(pipeline, tables, output=dest.config)
engine.execute(compiled, dest.config, credentials={})
```

## License

Apache-2.0.
