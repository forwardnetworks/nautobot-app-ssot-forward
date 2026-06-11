"""Support-bundle helpers for the Forward integration."""

from dataclasses import dataclass
from dataclasses import field
from datetime import datetime, timezone
from typing import Any

from .models import ForwardSyncReport

REDACTED_VALUE = "[REDACTED]"
REDACTION_KEYS = {
    "access_token",
    "api_key",
    "auth",
    "authorization",
    "client_id",
    "client_secret",
    "password",
    "refresh_token",
    "secret",
    "token",
    "username",
}

SHARING_PROFILES: dict[str, dict[str, set[str]]] = {
    "internal": {
        "allowlist": set(),
        "denylist": REDACTION_KEYS,
    },
    "external": {
        "allowlist": {
            "blocked",
            "create",
            "change_type",
            "configuration_status",
            "contract_version",
            "current",
            "current_policy",
            "delete_policy",
            "deactivated",
            "deleted",
            "diff_summary",
            "diagnostics",
            "errors",
            "failure_classification",
            "available_snapshots",
            "generated_at",
            "ignore",
            "last_failure",
            "last_run",
            "last_run_at",
            "last_support_bundle",
            "mode",
            "network_id",
            "notes",
            "no-change",
            "planned_models",
            "planned_counts",
            "profile_provided",
            "ready_profiles",
            "removed",
            "row_count",
            "sample_rows",
            "skipped",
            "source_summary",
            "status",
            "target_summary",
            "update",
            "write_mode",
            "write_policy",
            "write_ready",
            "write_summary",
            "missing_defaults",
            "missing_row_policy",
            "model_counts",
            "current",
            "baseline",
            "changed_files",
            "entries",
            "planned_models",
            "query_contract_version",
            "query_mode",
            "query_reference",
            "snapshot_id",
            "snapshot_metrics",
            "source_url",
            "sharing_profile",
            "last_run_at",
            "last_failure",
            "last_support_bundle",
            "last_run",
            "needs_attention_profiles",
            "update",
        },
        "denylist": REDACTION_KEYS | {"source_url"},
    },
}


def redact_support_bundle_payload(
    value: Any,
    *,
    sharing_profile: str = "internal",
    allowlist: set[str] | None = None,
    denylist: set[str] | None = None,
) -> Any:
    profile = SHARING_PROFILES.get(sharing_profile, SHARING_PROFILES["internal"])
    effective_allowlist = set(allowlist or profile["allowlist"])
    effective_denylist = set(denylist or profile["denylist"])
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).strip().lower()
            if normalized_key in effective_denylist:
                redacted[key] = REDACTED_VALUE if item not in ("", None) else item
                continue
            if effective_allowlist and normalized_key not in effective_allowlist:
                if isinstance(item, (dict, list, tuple)):
                    redacted[key] = redact_support_bundle_payload(
                        item,
                        sharing_profile=sharing_profile,
                        allowlist=effective_allowlist,
                        denylist=effective_denylist,
                    )
                else:
                    redacted[key] = REDACTED_VALUE
                continue
            redacted[key] = redact_support_bundle_payload(
                item,
                sharing_profile=sharing_profile,
                allowlist=effective_allowlist,
                denylist=effective_denylist,
            )
        return redacted
    if isinstance(value, list):
        return [
            redact_support_bundle_payload(
                item,
                sharing_profile=sharing_profile,
                allowlist=effective_allowlist,
                denylist=effective_denylist,
            )
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            redact_support_bundle_payload(
                item,
                sharing_profile=sharing_profile,
                allowlist=effective_allowlist,
                denylist=effective_denylist,
            )
            for item in value
        )
    return value


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
    sharing_profile: str = "external"
    query_contract_version: str = ""
    sample_rows: tuple[dict[str, Any], ...] = ()
    snapshot_metrics: dict[str, Any] = field(default_factory=dict)
    available_snapshots: tuple[dict[str, Any], ...] = ()
    planned_models: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    source_summary: dict[str, Any] = field(default_factory=dict)
    target_summary: dict[str, Any] = field(default_factory=dict)
    write_summary: dict[str, int] = field(default_factory=dict)
    diff_summary: dict[str, int] = field(default_factory=dict)
    write_policy: dict[str, Any] = field(default_factory=dict)
    configuration_status: dict[str, Any] = field(default_factory=dict)
    failure_classification: str = ""
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
            "query_contract_version": self.query_contract_version,
            "row_count": self.row_count,
            "sharing_profile": self.sharing_profile,
            "sample_rows": [dict(row) for row in self.sample_rows],
            "snapshot_metrics": dict(self.snapshot_metrics),
            "available_snapshots": [dict(item) for item in self.available_snapshots],
            "planned_models": list(self.planned_models),
            "notes": list(self.notes),
            "source_summary": dict(self.source_summary),
            "target_summary": dict(self.target_summary),
            "write_summary": dict(self.write_summary),
            "diff_summary": dict(self.diff_summary),
            "write_policy": dict(self.write_policy),
            "configuration_status": dict(self.configuration_status),
            "failure_classification": self.failure_classification,
            "diagnostics": dict(self.diagnostics),
        }

    def as_redacted_dict(self) -> dict[str, Any]:
        return self.as_shared_dict(self.sharing_profile)

    def as_shared_dict(self, sharing_profile: str = "external") -> dict[str, Any]:
        return redact_support_bundle_payload(self.as_dict(), sharing_profile=sharing_profile)


def build_support_bundle_pair(
    report: ForwardSyncReport,
    *,
    sample_size: int = 3,
    source_summary: dict[str, Any] | None = None,
    target_summary: dict[str, Any] | None = None,
    write_summary: dict[str, int] | None = None,
    diff_summary: dict[str, int] | None = None,
    write_policy: dict[str, Any] | None = None,
    configuration_status: dict[str, Any] | None = None,
    failure_classification: str | None = None,
    diagnostics: dict[str, Any] | None = None,
    sharing_profile: str = "external",
) -> tuple[ForwardSupportBundle, dict[str, Any]]:
    """Build the canonical bundle and its shared/redacted view together."""

    bundle = build_support_bundle(
        report,
        sample_size=sample_size,
        source_summary=source_summary,
        target_summary=target_summary,
        write_summary=write_summary,
        diff_summary=diff_summary,
        write_policy=write_policy,
        configuration_status=configuration_status,
        failure_classification=failure_classification,
        diagnostics=diagnostics,
        sharing_profile=sharing_profile,
    )
    return bundle, bundle.as_redacted_dict()


def classify_failure(
    *,
    write_summary: dict[str, int] | None = None,
    configuration_status: dict[str, Any] | None = None,
) -> str:
    """Classify the current run for support-triage output."""

    write_summary = dict(write_summary or {})
    configuration_status = dict(configuration_status or {})
    if not configuration_status.get("write_ready", True):
        return "configuration-blocked"
    if int(write_summary.get("blocked", 0) or 0) > 0:
        return "row-blocked"
    return "clean"


def build_support_bundle(
    report: ForwardSyncReport,
    *,
    sample_size: int = 3,
    source_summary: dict[str, Any] | None = None,
    target_summary: dict[str, Any] | None = None,
    write_summary: dict[str, int] | None = None,
    diff_summary: dict[str, int] | None = None,
    write_policy: dict[str, Any] | None = None,
    configuration_status: dict[str, Any] | None = None,
    failure_classification: str | None = None,
    diagnostics: dict[str, Any] | None = None,
    sharing_profile: str = "external",
) -> ForwardSupportBundle:
    sample_rows = tuple(report.rows[: max(int(sample_size or 0), 0)])
    resolved_failure_classification = (
        failure_classification
        if failure_classification is not None
        else classify_failure(
            write_summary=write_summary, configuration_status=configuration_status
        )
    )
    return ForwardSupportBundle(
        generated_at=datetime.now(timezone.utc).isoformat(),
        mode=report.mode,
        source_url=report.source_url,
        network_id=report.network_id,
        snapshot_id=report.snapshot_id,
        query_mode=report.query_mode,
        query_reference=report.query_reference,
        query_contract_version=report.query_contract_version,
        row_count=report.row_count,
        sharing_profile=sharing_profile if sharing_profile in SHARING_PROFILES else "external",
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
        write_summary=dict(write_summary or {}),
        diff_summary=dict(diff_summary or {}),
        write_policy=dict(write_policy or {}),
        configuration_status=dict(configuration_status or {}),
        failure_classification=resolved_failure_classification,
        diagnostics=dict(diagnostics or {}),
    )
