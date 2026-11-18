"""Keep a durable record of every applied delete override.

The delete governor refuses a model's deletes when they look wrong (too large a
share of the target, an empty source). An operator can force past that with an
override reason. That is deliberate and consequential, so each applied override is
recorded as its own row instead of living only in the latest support bundle, which
the next run replaces.

Only overrides that actually went ahead are recorded: a blocked delete changed
nothing and needs no audit trail. Recording must never fail the sync that already
deleted data, so a storage error is logged loudly and not raised.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def overrides_from_execution(write_execution: dict[str, Any] | None) -> dict[str, Any] | None:
    """Collapse a run's per-domain governance audits into one override record.

    Returns ``None`` when no override was applied. Pure: no database access.

    ``would_delete`` is what the governor counted as unmatched, which is an upper
    bound on what was removed: managed-object ownership still protects unmarked
    objects, so the number actually deleted can be lower.
    """
    summaries = (write_execution or {}).get("summaries") or {}
    overridden: list[dict[str, Any]] = []
    user = reason = ""
    for domain, summary in sorted(summaries.items()):
        audit = (summary or {}).get("delete_governance") if isinstance(summary, dict) else None
        if not isinstance(audit, dict):
            continue
        rows = audit.get("deletes_overridden") or []
        if not rows:
            continue
        info = audit.get("override") or {}
        user = user or str(info.get("user") or "")
        reason = reason or str(info.get("reason") or "")
        overridden.extend(
            {
                "domain": domain,
                "model": row.get("model"),
                "would_delete": row.get("would_delete"),
                "target_count": row.get("target_count"),
            }
            for row in rows
        )
    if not overridden:
        return None
    return {"user": user, "reason": reason, "overridden": overridden}


def record_delete_overrides(
    *, profile_name: str, snapshot_id: str, write_execution: dict[str, Any] | None
) -> bool:
    """Persist the run's applied override, if any. Returns whether a row was written."""
    record = overrides_from_execution(write_execution)
    if record is None:
        return False
    try:
        from forward_nautobot.models import ForwardConnectionProfile, ForwardDeleteOverride

        if ForwardDeleteOverride is None:
            return False
        profile = ForwardConnectionProfile.objects.filter(name=profile_name).first()
        ForwardDeleteOverride.objects.create(
            profile=profile,
            profile_name=profile_name,
            snapshot_id=snapshot_id,
            **record,
        )
    except Exception:  # noqa: BLE001 - never fail a sync that already applied its deletes
        logger.exception(
            "Could not record the applied delete override for profile %r; the override is "
            "still present in the run's support bundle.",
            profile_name,
        )
        return False
    return True
