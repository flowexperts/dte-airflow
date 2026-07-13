from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import ibis.expr.datatypes as dt

from dte.models.pipeline import DltSource
from dte.engine.duckdb_engine import DuckDBEngine
from dte.sources.dlt_loader import load_source

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
async def infer_schema(source: DltSource):
    engine = DuckDBEngine()
    try:
        table = load_source(source, engine.con)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    fields = [_walk(name, dtype) for name, dtype in table.schema().items()]
    return InferSchemaResponse(fields=fields)
