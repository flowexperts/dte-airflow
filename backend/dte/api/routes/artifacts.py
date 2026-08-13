from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from dte.artifacts import get_artifact_store
from dte.security.permissions import requires

router = APIRouter()


@router.get(
    "/artifacts/{key}",
    dependencies=[Depends(requires("run:read"))],
    response_class=Response,
)
async def get_artifact(key: str):
    """Stream a stored artifact by content hash.

    Rows carry `artifact://<key>` refs rather than blobs; this is where the
    document inspector fetches the bytes to render a PDF page.

    Guarded by `run:read` rather than a new permission: artifacts are run
    output, and anyone who may read a run's rows may read what those rows
    point at.
    """
    store = get_artifact_store()
    try:
        content = store.get(key)
    except ValueError as exc:
        # Malformed key — 400, not 404. A traversal attempt should not be
        # reported as "no such artifact".
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError:
        raise HTTPException(status_code=404, detail="Artifact not found") from None

    return Response(
        content=content,
        media_type=store.media_type(key) or "application/octet-stream",
        headers={
            # Content-addressed: the bytes under a key can never change, so
            # this is safe to cache forever.
            "Cache-Control": "public, max-age=31536000, immutable",
            "Content-Length": str(len(content)),
        },
    )
