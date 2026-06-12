"""Dry-run helpers for saved Forward payloads."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters import ForwardSourceAdapter
from .adapters import NautobotTargetAdapter
from .models import ForwardSyncReport
from .support import ForwardSupportBundle
from .support import build_support_bundle_pair
from .support import classify_failure
from .write_path import ForwardWritePlan
from .write_path import ForwardWritePlanner


@dataclass(slots=True)
class ForwardDryRunResult:
    """Result from a fixture-backed Forward dry run."""

    fixture_path: str
    source_summary: dict[str, Any]
    target_summary: dict[str, Any]
    write_summary: dict[str, int]
    configuration_status: dict[str, Any]
    failure_classification: str
    diff_summary: dict[str, int]
    report: ForwardSyncReport
    support_bundle: ForwardSupportBundle
    support_bundle_shared: dict[str, Any]
    write_plan: ForwardWritePlan

    def as_dict(self) -> dict[str, Any]:
        return {
            "fixture_path": self.fixture_path,
            "source_summary": dict(self.source_summary),
            "target_summary": dict(self.target_summary),
            "write_summary": dict(self.write_summary),
            "configuration_status": dict(self.configuration_status),
            "failure_classification": self.failure_classification,
            "diff_summary": dict(self.diff_summary),
            "report": self.report.as_dict(),
            "support_bundle": self.support_bundle.as_dict(),
            "support_bundle_shared": dict(self.support_bundle_shared),
            "write_plan": self.write_plan.as_dict(),
        }


def load_fixture_payload(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    fixture_path = Path(path)
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Fixture payload must be a JSON object.")
    rows_by_model: dict[str, list[dict[str, Any]]] = {}
    for model_name, rows in payload.items():
        if not isinstance(rows, list):
            continue
        cleaned_rows: list[dict[str, Any]] = []
        for row in rows:
            if isinstance(row, dict):
                cleaned_rows.append(dict(row))
        rows_by_model[str(model_name)] = cleaned_rows
    return rows_by_model


def run_fixture_dry_run(
    fixture_path: str | Path,
    *,
    model_names: tuple[str, ...] | list[str] | None = None,
    sample_size: int = 3,
    sharing_profile: str = "external",
) -> ForwardDryRunResult:
    rows_by_model = load_fixture_payload(fixture_path)
    selected_models = tuple(model_names or tuple(rows_by_model.keys()))
    source = ForwardSourceAdapter(model_names=selected_models)
    target = NautobotTargetAdapter(model_names=selected_models)
    for model_name in selected_models:
        source.load_rows(model_name, rows_by_model.get(model_name, []))
    write_plan = ForwardWritePlanner().plan(source, target)
    row_count = sum(len(rows_by_model.get(model_name, [])) for model_name in selected_models)
    report = ForwardSyncReport(
        mode="dry-run",
        source_url="fixture://local",
        network_id="fixture",
        snapshot_id="fixture",
        query_mode="fixture",
        query_reference=str(fixture_path),
        row_count=row_count,
        query_contract_version="fixture",
        rows=tuple(
            row
            for model_name in selected_models
            for row in rows_by_model.get(model_name, [])
        ),
        planned_models=selected_models,
        notes=("Fixture-backed dry run.",),
    )
    failure_classification = (
        "clean"
        if not write_plan.configuration_status.get("profile_provided")
        else classify_failure(
            write_summary=write_plan.summary,
            configuration_status=write_plan.configuration_status,
        )
    )
    support_bundle, support_bundle_shared = build_support_bundle_pair(
        report,
        sample_size=sample_size,
        source_summary=source.as_support_summary(),
        target_summary=target.as_support_summary(),
        write_summary=write_plan.summary,
        diff_summary=write_plan.diff_summary,
        write_policy=write_plan.slice_policies,
        configuration_status=write_plan.configuration_status,
        failure_classification=failure_classification,
        diagnostics={
            "write_summary": write_plan.summary,
            "configuration_status": write_plan.configuration_status,
            "diff_summary": write_plan.diff_summary,
            "write_policy": write_plan.slice_policies,
            "diff_detail": write_plan.diff_detail,
            "fixture_path": str(fixture_path),
        },
        sharing_profile=sharing_profile,
    )
    return ForwardDryRunResult(
        fixture_path=str(fixture_path),
        source_summary=source.as_support_summary(),
        target_summary=target.as_support_summary(),
        write_summary=write_plan.summary,
        configuration_status=write_plan.configuration_status,
        failure_classification=failure_classification,
        diff_summary=write_plan.diff_summary,
        report=report,
        support_bundle=support_bundle,
        support_bundle_shared=support_bundle_shared,
        write_plan=write_plan,
    )
