"""Support-bundle helpers for the Forward integration."""

from dataclasses import dataclass
from dataclasses import field
from datetime import datetime, timezone
from typing import Any

from .models import ForwardSyncReport


@dataclass(slots=True)
class ForwardSupportBundle:
    """Sanitized troubleshooting payload built from a sync report."""

    generated_at: str
    mode: str
    source_url: str
    network_id: str
    snapshot_id: str
    query_mode: str
    query_reference: str
    row_count: int
    sample_rows: tuple[dict[str, Any], ...] = ()
    snapshot_metrics: dict[str, Any] = field(default_factory=dict)
    available_snapshots: tuple[dict[str, Any], ...] = ()
    planned_models: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    source_summary: dict[str, Any] = field(default_factory=dict)
    target_summary: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "mode": self.mode,
            "source_url": self.source_url,
            "network_id": self.network_id,
            "snapshot_id": self.snapshot_id,
            "query_mode": self.query_mode,
            "query_reference": self.query_reference,
            "row_count": self.row_count,
            "sample_rows": [dict(row) for row in self.sample_rows],
            "snapshot_metrics": dict(self.snapshot_metrics),
            "available_snapshots": [dict(item) for item in self.available_snapshots],
            "planned_models": list(self.planned_models),
            "notes": list(self.notes),
            "source_summary": dict(self.source_summary),
            "target_summary": dict(self.target_summary),
            "diagnostics": dict(self.diagnostics),
        }


def build_support_bundle(
    report: ForwardSyncReport,
    *,
    sample_size: int = 3,
    source_summary: dict[str, Any] | None = None,
    target_summary: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> ForwardSupportBundle:
    sample_rows = tuple(report.rows[: max(int(sample_size or 0), 0)])
    return ForwardSupportBundle(
        generated_at=datetime.now(timezone.utc).isoformat(),
        mode=report.mode,
        source_url=report.source_url,
        network_id=report.network_id,
        snapshot_id=report.snapshot_id,
        query_mode=report.query_mode,
        query_reference=report.query_reference,
        row_count=report.row_count,
        sample_rows=sample_rows,
        snapshot_metrics=dict(report.snapshot_metrics),
        available_snapshots=tuple(
            {
                "id": snapshot.id,
                "state": snapshot.state,
                "created_at": snapshot.created_at,
                "processed_at": snapshot.processed_at,
                "label": snapshot.label,
            }
            for snapshot in report.available_snapshots
        ),
        planned_models=report.planned_models,
        notes=report.notes,
        source_summary=dict(source_summary or {}),
        target_summary=dict(target_summary or {}),
        diagnostics=dict(diagnostics or {}),
    )
