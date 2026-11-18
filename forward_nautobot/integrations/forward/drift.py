"""Explain what a sync would change, and why, one slice at a time.

nautobot-ssot shows the object-by-object diff; it does not say why a slice looks
the way it does or what to do about it. This reads the diff the write planner
already computes and turns it into short statements an operator can act on:
which slices would create, update or delete, which fields drive the updates, and
why deletes are or are not going to happen.

Counts, slice names and field names only. Never field values, and never the
free-text reason an operator types for a delete override, so the output is safe
to leave in a shared support bundle.

Pure: takes the plan's dicts, returns a dict. No Forward or database access.
"""

from __future__ import annotations

from typing import Any

#: When at least this share of the objects Nautobot already holds for a slice would
#: change, the cause is more likely a Forward-side rename than real drift.
LARGE_UPDATE_SHARE = 0.5
#: Fields named per slice in an explanation.
TOP_FIELDS = 3


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def explain_drift(
    diff_detail: dict[str, Any] | None,
    configuration_status: dict[str, Any] | None = None,
    delete_governance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return ``{"drift_slices": [...], "notes": [...]}`` for the given plan details.

    Key names are specific on purpose: sharing allowlists by key name at every
    depth, so generic names such as ``slice`` or ``action`` would widen what every
    other part of a bundle reveals.
    """
    diff_detail = diff_detail or {}
    configuration_status = configuration_status or {}
    changed_by_slice = diff_detail.get("changed_fields") or {}
    slices: list[dict[str, Any]] = []

    for slug, counts in (diff_detail.get("models") or {}).items():
        create = _int((counts or {}).get("create"))
        update = _int((counts or {}).get("update"))
        unchanged = _int((counts or {}).get("no-change"))
        if not (create or update):
            continue
        parts: list[str] = []
        action = ""
        if create:
            parts.append(f"{create} object(s) exist in Forward but not in Nautobot")
        if update:
            fields = list((changed_by_slice.get(slug) or {}).items())[:TOP_FIELDS]
            named = ", ".join(f"{name} ({count})" for name, count in fields)
            parts.append(
                f"{update} object(s) differ" + (f"; most-changed fields: {named}" if named else "")
            )
            existing = update + unchanged
            if existing and update / existing >= LARGE_UPDATE_SHARE:
                parts.append(
                    "a large share of existing objects changed, which usually means a "
                    "naming or normalization change in Forward rather than real drift"
                )
                action = "Check recent Forward changes before applying this slice."
        slices.append(
            {
                "drift_slice": slug,
                "create": create,
                "update": update,
                "drift_explanation": "; ".join(parts) + ".",
                "drift_action": action,
            }
        )

    return {
        "drift_slices": slices,
        "notes": _delete_notes(configuration_status, delete_governance or {}),
    }


def _delete_notes(configuration_status: dict[str, Any], governance: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    if configuration_status.get("filtered_scope"):
        notes.append(
            "Filtered run: only creates and updates are applied. A device or cloud filter "
            "never drives deletes."
        )
    if configuration_status.get("destructive_reconciliation_enabled") is False:
        completeness = configuration_status.get("snapshot_completeness") or {}
        reason = str(completeness.get("reason") or "").strip()
        notes.append("Deletes are disabled for this snapshot" + (f": {reason}." if reason else "."))
    elif configuration_status.get("delete_policy") == "ignore":
        notes.append("The profile's delete policy is 'ignore', so nothing is deleted.")

    for domain, audit in sorted(governance.items()):
        if not isinstance(audit, dict):
            continue
        for row in audit.get("deletes_blocked") or []:
            notes.append(
                f"{domain}: {_int(row.get('would_delete'))} delete(s) of {row.get('model')} "
                "were blocked by the delete governor; review them, or re-run with an "
                "override reason if they are intended."
            )
        for row in audit.get("deletes_overridden") or []:
            notes.append(
                f"{domain}: {_int(row.get('would_delete'))} delete(s) of {row.get('model')} "
                "went ahead under an operator override."
            )
    return notes
