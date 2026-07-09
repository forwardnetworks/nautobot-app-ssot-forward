"""Pure Prometheus text-exposition rendering for Forward metrics.

Kept free of Django imports so the rendering logic is unit-testable; the
``forward_metrics`` management command supplies the ORM data.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any


def parse_epoch(value: str) -> float | None:
    """Parse an ISO-8601 timestamp string to a Unix epoch, or None if unparseable."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _escape_label(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _metric(lines: list[str], name: str, help_text: str, value: Any) -> None:
    lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} gauge")
    lines.append(f"{name} {value}")


def render_prometheus(
    records: Iterable[Any],
    *,
    now_epoch: float,
    ssot_sync_count: int | None = None,
) -> str:
    """Render Forward metrics for the given profile records.

    Each record needs ``name``, ``write_ready``, ``last_run_at``, ``last_failure``.
    """
    records = list(records)
    lines: list[str] = []

    _metric(
        lines, "forward_profiles_total", "Configured Forward connection profiles.", len(records)
    )
    _metric(
        lines,
        "forward_profiles_ready",
        "Profiles with all write prerequisites satisfied.",
        sum(1 for r in records if r.write_ready),
    )
    _metric(
        lines,
        "forward_profiles_needs_attention",
        "Profiles missing write prerequisites.",
        sum(1 for r in records if not r.write_ready),
    )

    lines.append("# HELP forward_profile_last_run_timestamp_seconds Unix time of the last run.")
    lines.append("# TYPE forward_profile_last_run_timestamp_seconds gauge")
    lines.append("# HELP forward_profile_last_run_age_seconds Seconds since the last run.")
    lines.append("# TYPE forward_profile_last_run_age_seconds gauge")
    lines.append("# HELP forward_profile_last_run_failed 1 if the last run recorded a failure.")
    lines.append("# TYPE forward_profile_last_run_failed gauge")
    for record in records:
        label = f'{{profile="{_escape_label(record.name)}"}}'
        epoch = parse_epoch(record.last_run_at)
        if epoch is not None:
            lines.append(f"forward_profile_last_run_timestamp_seconds{label} {int(epoch)}")
            lines.append(f"forward_profile_last_run_age_seconds{label} {int(now_epoch - epoch)}")
        failed = 1 if str(record.last_failure or "").strip() else 0
        lines.append(f"forward_profile_last_run_failed{label} {failed}")

    if ssot_sync_count is not None:
        _metric(
            lines,
            "forward_ssot_syncs_total",
            "Recorded nautobot-ssot Sync rows (all data sources).",
            int(ssot_sync_count),
        )

    return "\n".join(lines) + "\n"
