"""Which providers are configured well enough to be worth offering.

A comparison came back with two empty columns and a per-row SDK message:
"Could not resolve authentication method." The key was simply unset. The
wizard had offered Claude and OpenAI exactly as it offers regex, taken an
estimate, launched a sweep, and only then surfaced the problem — as a
property of the *documents*, which is where a reader naturally concludes
the model is bad at the task rather than absent.

Same shape as the regex-needs-a-pattern gate: a provider that cannot
succeed should not be offered, and the reason should name the fix.

Keys are Airflow connections (plan 072): `anthropic_default` /
`openai_default`, or whichever connection a step names.

**Configuration, not validity.** A present-but-expired key still has to
fail at call time. Proving a key works needs a billable request, and the
answer would be stale the moment it is revoked — so this reports only
whether a connection exists, and says so.

**No secret is returned.** Only conn ids cross the wire.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from dte.security.permissions import requires

router = APIRouter()

# Provider → its Airflow default conn id. `regex` is absent because it needs
# nothing; it is what makes a free comparison possible and must never gate.
_DEFAULT_CONN: dict[str, str] = {
    "claude": "anthropic_default",
    "openai": "openai_default",
}


def _connections(provider: str) -> list[str]:
    from dte.airflow import connections

    try:
        return connections.model_connections(provider)
    except ImportError:  # the Airflow provider package isn't installed
        return []


@router.get("/providers/structure", dependencies=[Depends(requires("pipeline:read"))])
async def structure_provider_status():
    """Per-provider readiness for the `structure` step."""
    from dte.models.pipeline import StructureStep

    declared = StructureStep.model_fields["provider"].annotation.__args__
    providers: dict[str, dict] = {}
    for name in declared:
        default = _DEFAULT_CONN.get(name)
        if default is None:
            providers[name] = {"configured": True, "reason": None, "connections": []}
            continue
        conns = await asyncio.to_thread(_connections, name)
        ok = default in conns
        providers[name] = {
            "configured": ok,
            "reason": None if ok else (
                f"Airflow connection {default!r} does not exist. Create it in "
                f"Airflow → Admin → Connections with the API key as password, "
                f"or compare against regex, which needs no key."
            ),
            "connections": conns,
        }
    return {"providers": providers}
