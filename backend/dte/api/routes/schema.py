from __future__ import annotations
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import ibis.expr.datatypes as dt

from dte.models.pipeline import SourceCreate as Source
from dte.engine.duckdb_engine import DuckDBEngine
from dte.sources.loader import load_source
from dte.api.deps import get_connection_store
from dte.store.base import ConnectionStore

router = APIRouter()


class SchemaFieldNode(BaseModel):
    """One node in the schema tree.

    Leaf: `type` is the ibis dtype string, `children` is None.
    Branch (STRUCT): `type` is "struct", `children` lists its fields.
    """
    name: str
    type: str
    children: list["SchemaFieldNode"] | None = None


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


@router.post("/schema/infer", response_model=InferSchemaResponse)
async def infer_schema(
    source: Source,
    c_store: ConnectionStore = Depends(get_connection_store),
):
    """Infer schema for an in-flight (unsaved) source. Requires
    `source.connection_id` to reference an existing Connection so the
    loader can decrypt credentials."""
    conn = await c_store.get(source.connection_id)
    if not conn:
        raise HTTPException(
            status_code=422,
            detail=f"Connection '{source.connection_id}' does not exist",
        )
    engine = DuckDBEngine()
    try:
        table = load_source(source, engine.con, conn.credentials_dict())
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    fields = [_walk(name, dtype) for name, dtype in table.schema().items()]
    return InferSchemaResponse(fields=fields)
