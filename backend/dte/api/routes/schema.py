from __future__ import annotations

import ibis.expr.datatypes as dt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dte.api.deps import get_connection_store
from dte.automap import Field as _AField, automap as _automap
from dte.engine.backend_registry import BackendRegistry
from dte.engine.duckdb_engine import DuckDBEngine
from dte.models.pipeline import SourceBase as Source
from dte.security.permissions import requires
from dte.sources.loader import load_source
from dte.store.base import ConnectionStore

router = APIRouter()


class SchemaFieldNode(BaseModel):
    """One node in the schema tree.

    Leaf: `type` is the ibis dtype string, `children` is None.
    Branch (STRUCT): `type` is "struct", `children` lists its fields.
    """
    name: str
    type: str
    children: list[SchemaFieldNode] | None = None


class InferSchemaResponse(BaseModel):
    fields: list[SchemaFieldNode]


def _walk(name: str, dtype: dt.DataType) -> SchemaFieldNode:
    if isinstance(dtype, dt.Struct):
        return SchemaFieldNode(
            name=name,
            type="struct",
            children=[_walk(k, v) for k, v in dtype.fields.items()],
        )
    return SchemaFieldNode(name=name, type=str(dtype))


@router.post("/schema/infer", response_model=InferSchemaResponse, dependencies=[Depends(requires("source:read"))])
async def infer_schema(
    source: Source,
    table: str | None = None,
    c_store: ConnectionStore = Depends(get_connection_store),
):
    """Infer schema for an in-flight (unsaved) source. Requires
    `source.connection_id` to reference an existing Connection so the
    loader can decrypt credentials.

    `table` — required for `sql_database` sources (they no longer carry a
    table in their own config; which table is read is a
    per-pipeline-per-use decision, so the caller supplies it here for a
    preview of a table not yet saved on any pipeline). Ignored for every
    other kind."""
    conn = await c_store.get(source.connection_id)
    if not conn:
        raise HTTPException(
            status_code=422,
            detail=f"Connection '{source.connection_id}' does not exist",
        )
    engine = DuckDBEngine()
    registry = BackendRegistry(duckdb_con=engine.con)
    try:
        result_table = load_source(source, registry, conn, conn.credentials, table=table)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    fields = [_walk(name, dtype) for name, dtype in result_table.schema().items()]
    return InferSchemaResponse(fields=fields)


class AutomapField(BaseModel):
    name: str
    type: str = ""


class AutomapRequest(BaseModel):
    source_fields: list[AutomapField]
    dest_fields: list[AutomapField]
    use_llm: bool = True


class AutomapMatch(BaseModel):
    dest: str
    source: str | None = None
    confidence: float = 0.0
    via: str | None = None
    warning: str | None = None


class AutomapResponse(BaseModel):
    matches: list[AutomapMatch]
    unmatched_source: list[str]
    llm_error: str | None = None


@router.post("/schema/automap", response_model=AutomapResponse, dependencies=[Depends(requires("source:read"))])
async def automap_fields(body: AutomapRequest):
    """Propose a source→destination column mapping.

    Pure computation over two field lists the caller already has — no
    store access, no source loading. The optional LLM pass is the only
    I/O, and its failure is reported in `llm_error` rather than failing
    the request: the heuristic answer is still worth showing.
    """
    result = _automap(
        [_AField(f.name, f.type) for f in body.source_fields],
        [_AField(f.name, f.type) for f in body.dest_fields],
        use_llm=body.use_llm,
    )
    return AutomapResponse(
        matches=[AutomapMatch(**vars(m)) for m in result.matches],
        unmatched_source=result.unmatched_source,
        llm_error=result.llm_error,
    )
