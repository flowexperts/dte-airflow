from __future__ import annotations

import re
from typing import IO

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.responses import StreamingResponse

from dte.artifacts import get_artifact_store
from dte.security.permissions import requires

router = APIRouter()

# Only the single-range forms, which is all any PDF viewer sends. A
# multi-range request would need a multipart/byteranges body; declining to
# parse it means falling back to the whole document, which is correct but
# slow — never wrong.
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")

# Chunk size for streamed bodies. Large enough that syscall overhead is
# irrelevant, small enough that a concurrent reader's memory is bounded
# regardless of document size.
_CHUNK = 256 * 1024


def parse_range(header: str | None, total: int) -> tuple[int, int] | None | bool:
    """Resolve a `Range` header to an inclusive `(start, end)` byte span.

    Three outcomes, deliberately distinct:
      `None`  — no range, or one we decline to parse. Serve the whole body.
                RFC 7233 §3.1 says an unrecognised range MUST be ignored, so
                a proxy that rewrites the header degrades to a full download
                rather than a 416.
      `False` — syntactically valid but unsatisfiable. Caller must 416.
      tuple   — the resolved span, clamped to the artifact.
    """
    if not header:
        return None
    m = _RANGE_RE.match(header.strip())
    if not m:
        return None

    raw_start, raw_end = m.group(1), m.group(2)
    if not raw_start and not raw_end:
        return None
    if total == 0:
        return False

    if not raw_start:
        # Suffix form, `bytes=-N`: the last N bytes. This is the *first*
        # request pdf.js makes — a PDF's cross-reference trailer lives at the
        # end of the file, so the viewer reads backwards before anything else.
        length = int(raw_end)
        if length == 0:
            return False
        start, end = max(0, total - length), total - 1
    else:
        start = int(raw_start)
        if start >= total:
            return False
        # An end past the last byte is clamped, not rejected: a viewer that
        # asks for more than exists should get what exists.
        end = min(int(raw_end), total - 1) if raw_end else total - 1
        if end < start:
            return False

    return start, end


def _stream(fh: IO[bytes], start: int, length: int):
    """Yield `length` bytes from `start`, a chunk at a time."""
    try:
        fh.seek(start)
        remaining = length
        while remaining > 0:
            chunk = fh.read(min(_CHUNK, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        fh.close()


@router.get(
    "/artifacts/{key}",
    dependencies=[Depends(requires("run:read"))],
    response_class=Response,
)
async def get_artifact(key: str, range_header: str | None = Header(None, alias="Range")):
    """Stream a stored artifact by content hash.

    Rows carry `artifact://<key>` refs rather than blobs; this is where the
    document inspector fetches the bytes to render a PDF page.

    Served as a stream with byte-range support so a 500-page document costs
    the client only the pages it looks at and the server only a chunk of RSS
    per request — reading the whole artifact to answer either would put a
    hard ceiling on document size.

    Guarded by `run:read` rather than a new permission: artifacts are run
    output, and anyone who may read a run's rows may read what those rows
    point at.
    """
    store = get_artifact_store()
    try:
        total = store.size(key)
    except ValueError as exc:
        # Malformed key — 400, not 404. A traversal attempt should not be
        # reported as "no such artifact".
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError:
        raise HTTPException(status_code=404, detail="Artifact not found") from None

    media_type = store.media_type(key) or "application/octet-stream"
    headers = {
        # Content-addressed: the bytes under a key can never change, so this
        # is safe to cache forever.
        "Cache-Control": "public, max-age=31536000, immutable",
        "Accept-Ranges": "bytes",
    }

    resolved = parse_range(range_header, total)

    if resolved is False:
        # 416 must still report the real length, or the client cannot work
        # out what it should have asked for.
        raise HTTPException(
            status_code=416,
            detail="Requested range not satisfiable",
            headers={**headers, "Content-Range": f"bytes */{total}"},
        )

    if resolved is None:
        start, end, status = 0, total - 1, 200
    else:
        start, end = resolved
        status = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"

    length = max(0, end - start + 1)
    headers["Content-Length"] = str(length)

    return StreamingResponse(
        _stream(store.open_stream(key), start, length),
        status_code=status,
        media_type=media_type,
        headers=headers,
    )
