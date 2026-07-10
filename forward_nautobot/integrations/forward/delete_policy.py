"""Delete governance for the contrib sync path.

``contrib`` ``source.sync_to(target)`` delete-reconciles the whole target table, so
deleting is opt-in (``delete_policy="delete"``). Even then it is gated *per model*
so an under-collected slice — a source that returned zero or a small fraction of
reality — cannot wipe Nautobot. An operator can intentionally proceed by supplying
an override reason, which is recorded (who / why / when / what) in the run audit.

The math here is pure and unit-tested; the contrib runners feed it adapter counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# A slice that would delete more than this fraction of an existing model is
# refused unless overridden. Mirrors the legacy write-executor safeguard.
DEFAULT_MAX_DELETE_FRACTION = 0.25


@dataclass
class DeleteControls:
    """Operator-supplied delete knobs threaded from the Job to the runners."""

    override: bool = False
    override_reason: str = ""
    user: str = ""
    max_fraction: float = DEFAULT_MAX_DELETE_FRACTION


@dataclass
class DeleteDecision:
    model: str
    target_count: int
    source_count: int
    would_delete: int
    allowed: bool
    reason: str  # "" when trivially allowed; a note when blocked or overridden


def evaluate_model_deletes(
    model: str,
    *,
    target_count: int,
    source_count: int,
    would_delete: int,
    max_fraction: float = DEFAULT_MAX_DELETE_FRACTION,
    override: bool = False,
) -> DeleteDecision:
    """Decide whether a single model's deletions may proceed."""

    def decide(allowed: bool, reason: str) -> DeleteDecision:
        return DeleteDecision(model, target_count, source_count, would_delete, allowed, reason)

    if would_delete <= 0:
        return decide(True, "")

    # Zero-rows gate: the source returned nothing but targets exist — almost always
    # an upstream fetch problem, not a real teardown.
    if target_count > 0 and source_count == 0:
        if override:
            return decide(True, f"override: source returned 0 rows (would delete {would_delete})")
        return decide(
            False, f"blocked: source returned 0 rows; refusing to delete {would_delete} objects"
        )

    # Fraction gate: refuse deleting more than max_fraction of the model.
    if target_count and 0.0 < max_fraction < 1.0 and would_delete > target_count * max_fraction:
        pct = would_delete / target_count
        if override:
            return decide(
                True,
                f"override: {would_delete}/{target_count} ({pct:.0%}) exceeds {max_fraction:.0%}",
            )
        return decide(
            False,
            f"blocked: {would_delete}/{target_count} ({pct:.0%}) exceeds max delete fraction {max_fraction:.0%}",
        )

    return decide(True, "")


def evaluate_adapter_deletes(
    source: Any,
    target: Any,
    model_names: list[str],
    *,
    max_fraction: float = DEFAULT_MAX_DELETE_FRACTION,
    override: bool = False,
) -> list[DeleteDecision]:
    """Evaluate deletions for each model by comparing source vs target unique ids."""
    decisions: list[DeleteDecision] = []
    for model in model_names:
        target_uids = {obj.get_unique_id() for obj in target.get_all(model)}
        source_uids = {obj.get_unique_id() for obj in source.get_all(model)}
        would_delete = len(target_uids - source_uids)
        decisions.append(
            evaluate_model_deletes(
                model,
                target_count=len(target_uids),
                source_count=len(source_uids),
                would_delete=would_delete,
                max_fraction=max_fraction,
                override=override,
            )
        )
    return decisions


def build_delete_audit(
    decisions: list[DeleteDecision],
    *,
    allow_delete: bool,
    user: str = "",
    override_reason: str = "",
    at: str = "",
) -> dict:
    """Summarize delete decisions into a persisted-friendly audit record."""
    active = [d for d in decisions if d.would_delete > 0]
    blocked = [d for d in active if not d.allowed]
    overridden = [d for d in active if d.allowed and d.reason.startswith("override")]
    allowed = [d for d in active if d.allowed and not d.reason.startswith("override")]

    def _rows(items: list[DeleteDecision]) -> list[dict]:
        return [
            {
                "model": d.model,
                "would_delete": d.would_delete,
                "target_count": d.target_count,
                "reason": d.reason,
            }
            for d in items
        ]

    audit: dict[str, Any] = {
        "allow_delete": bool(allow_delete),
        "deletes_allowed_models": [d.model for d in allowed],
        "deletes_blocked": _rows(blocked),
        "deletes_overridden": _rows(overridden),
    }
    if overridden:
        audit["override"] = {"user": user, "reason": override_reason, "at": at}
    return audit


def allowed_models(decisions: list[DeleteDecision]) -> set[str]:
    """The set of model names whose deletions the governor permits."""
    return {d.model for d in decisions if d.allowed}
