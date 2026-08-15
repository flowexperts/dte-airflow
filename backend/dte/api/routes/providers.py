"""Which providers are configured well enough to be worth offering.

A comparison came back with two empty columns and a per-row SDK message:
"Could not resolve authentication method." The key was simply unset. The
wizard had offered Claude and OpenAI exactly as it offers regex, taken an
estimate, launched a sweep, and only then surfaced the problem — as a
property of the *documents*, which is where a reader naturally concludes
the model is bad at the task rather than absent.

Same shape as the regex-needs-a-pattern gate: a provider that cannot
succeed should not be offered, and the reason should name the fix.

**Configuration, not validity.** A present-but-expired key still has to
fail at call time. Proving a key works needs a billable request, and the
answer would be stale the moment it is revoked — so this reports only
whether anything was supplied, and says so.

**The value is never returned.** A readiness probe that echoes the secret
turns a convenience into a disclosure on every page load.
"""
from __future__ import annotations

import os

from fastapi import APIRouter

router = APIRouter()

# Provider → the environment variable its SDK reads. `regex` is absent
# because it needs nothing; it is what makes a free comparison possible and
# must never gate.
_REQUIRED_ENV: dict[str, str] = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def _configured(var: str) -> bool:
    # Compose writes `ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}`, so the
    # variable exists and is empty when nothing supplied it. Presence is not
    # the test — a non-blank value is.
    return bool((os.environ.get(var) or "").strip())


@router.get("/providers/structure")
async def structure_provider_status():
    """Per-provider readiness for the `structure` step."""
    from dte.models.pipeline import StructureStep

    declared = StructureStep.model_fields["provider"].annotation.__args__
    providers: dict[str, dict] = {}
    for name in declared:
        var = _REQUIRED_ENV.get(name)
        if var is None:
            providers[name] = {"configured": True, "reason": None}
            continue
        ok = _configured(var)
        providers[name] = {
            "configured": ok,
            "reason": None if ok else (
                f"{var} is not set on the server. Add it to the environment "
                f"and restart, or compare against regex, which needs no key."
            ),
        }
    return {"providers": providers}
