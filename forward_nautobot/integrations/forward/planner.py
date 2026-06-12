"""Ingestion planning for the Forward integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from importlib import resources

from .adapters import ForwardSourceAdapter
from .adapters import NautobotTargetAdapter
from .client import ForwardClient
from ...models import ForwardConnectionProfileRecord
from .models import ForwardConnectionSettings
from .models import ForwardQuerySpec
from .models import ForwardSyncReport
from .registry import ForwardModelMapping
from .registry import get_model_mapping
from .registry import get_model_mappings
from .write_contract import ForwardWriteContractAdvisor
from .write_path import ForwardWriteOperation
from .write_path import ForwardWritePlan
from .write_path import ForwardWritePlanner


@dataclass(slots=True)
class ForwardIngestionRequest:
    """Inputs for a raw ingestion pass."""

    connection: ForwardConnectionSettings
    model_names: tuple[str, ...] = ()
    fetch_all: bool = True
    limit: int | None = None
    offset: int = 0
    item_format: str = "JSON"
    snapshot_id: str | None = None
    connection_profile: ForwardConnectionProfileRecord | None = None


@dataclass(slots=True)
class ForwardIngestionPlan:
    """Raw ingestion plan for the selected Forward model slices."""

    source: ForwardSourceAdapter
    target: NautobotTargetAdapter
    reports: tuple[ForwardSyncReport, ...]
    write_plan: ForwardWritePlan
    diff_summary: dict[str, int]
    diff_detail: dict[str, Any]

    @property
    def source_summary(self) -> dict[str, Any]:
        return self.source.as_support_summary()

    @property
    def target_summary(self) -> dict[str, Any]:
        return self.target.as_support_summary()

    @property
    def write_summary(self) -> dict[str, int]:
        return dict(self.write_plan.summary)

    @property
    def configuration_status(self) -> dict[str, Any]:
        return dict(self.write_plan.configuration_status)


class ForwardIngestionPlanner:
    """Load Forward rows and prepare them for Nautobot writes without mutation."""

    def __init__(self, client: ForwardClient):
        self.client = client

    @staticmethod
    def _query_text_for(mapping: ForwardModelMapping) -> str:
        package = resources.files("forward_nautobot.integrations.forward.queries")
        return (package / mapping.forward_query_file).read_text(encoding="utf-8")

    @staticmethod
    def _row_key(mapping: ForwardModelMapping, row: dict[str, Any]) -> str:
        key_parts: list[str] = []
        for field_name in mapping.identity_fields:
            value = row.get(field_name)
            if value is None:
                raise ValueError(
                    f"Forward row for `{mapping.slug}` is missing identity field `{field_name}`."
                )
            value_text = str(value).strip()
            if not value_text:
                raise ValueError(
                    f"Forward row for `{mapping.slug}` has an empty identity field `{field_name}`."
                )
            key_parts.append(value_text)
        return "|".join(key_parts)

    @staticmethod
    def _configuration_status(
        *,
        profile: ForwardConnectionProfileRecord | None,
        model_mappings: tuple[ForwardModelMapping, ...],
    ) -> dict[str, Any]:
        return {
            "profile_provided": profile is not None,
            "write_ready": bool(profile.write_ready) if profile is not None else False,
            "missing_defaults": list(profile.missing_write_defaults()) if profile is not None else [],
            "delete_policy": getattr(profile, "delete_policy", "ignore") if profile is not None else "ignore",
            "slice_policies": {
                mapping.slug: {
                    "write_mode": mapping.write_mode,
                    "missing_row_policy": mapping.missing_row_policy,
                }
                for mapping in model_mappings
            },
        }

    @staticmethod
    def _slice_policy_for(mapping: ForwardModelMapping) -> dict[str, str]:
        return {
            "write_mode": mapping.write_mode,
            "missing_row_policy": mapping.missing_row_policy,
        }

    @staticmethod
    def _scope_values_for_source(
        source: ForwardSourceAdapter,
        source_slug: str,
    ) -> tuple[str, ...]:
        try:
            mapping = get_model_mapping(source_slug)
        except Exception:
            return ()
        records = source.records.get(mapping.slug, {})
        if not records:
            return ()
        field_name = mapping.identity_fields[0] if mapping.identity_fields else "name"
        values: list[str] = []
        for record in records.values():
            value = record.fields.get(field_name)
            if value is None:
                continue
            value_text = str(value).strip()
            if value_text:
                values.append(value_text)
        return tuple(dict.fromkeys(values))

    def _query_parameters_for(
        self,
        mapping: ForwardModelMapping,
        source: ForwardSourceAdapter,
    ) -> dict[str, list[str]]:
        if not mapping.query_parameters:
            return {}
        parameters: dict[str, list[str]] = {}
        for parameter_name, source_slugs in mapping.query_parameters.items():
            scoped_values: list[str] = []
            for source_slug in source_slugs:
                scoped_values.extend(self._scope_values_for_source(source, source_slug))
            parameters[parameter_name] = list(dict.fromkeys(scoped_values))
        return parameters

    @staticmethod
    def _merge_counts(
        base: dict[str, int],
        update: dict[str, int],
    ) -> dict[str, int]:
        merged = dict(base)
        for key, value in update.items():
            merged[key] = int(merged.get(key, 0) or 0) + int(value or 0)
        return merged

    def _build_full_plan(
        self,
        *,
        source: ForwardSourceAdapter,
        target: NautobotTargetAdapter,
        profile: ForwardConnectionProfileRecord | None,
    ) -> tuple[ForwardWritePlan, dict[str, int], dict[str, Any]]:
        writer = ForwardWritePlanner()
        write_plan = writer.plan(source, target, profile=profile)
        return write_plan, dict(write_plan.diff_summary), dict(write_plan.diff_detail)

    def _build_delta_plan(
        self,
        *,
        mapping: ForwardModelMapping,
        rows: list[dict[str, Any]],
        profile: ForwardConnectionProfileRecord | None,
    ) -> tuple[
        ForwardWritePlan,
        dict[str, int],
        dict[str, Any],
        tuple[dict[str, Any], ...],
        tuple[dict[str, Any], ...],
    ]:
        advisor = ForwardWriteContractAdvisor()
        operations: list[ForwardWriteOperation] = []
        summary = {"create": 0, "update": 0, "deleted": 0, "blocked": 0, "no-change": 0}
        source_rows: list[dict[str, Any]] = []
        diff_entries: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            before = dict(row.get("before") or {}) if isinstance(row.get("before"), dict) else {}
            after = dict(row.get("after") or {}) if isinstance(row.get("after"), dict) else {}
            if after and before:
                action = "update"
                data = after
            elif after:
                action = "create"
                data = after
            elif before:
                action = "delete"
                data = before
            else:
                continue
            record_key = self._row_key(mapping, data)
            blocked_by: tuple[str, ...] = ()
            if action != "delete":
                readiness = advisor.readiness_for(mapping, profile=profile, row=data)
                blocked_by = readiness.blocked_by
                if blocked_by:
                    summary["blocked"] += 1
            operations.append(
                ForwardWriteOperation(
                    model_slug=mapping.slug,
                    record_key=record_key,
                    nautobot_scope=mapping.nautobot_scope,
                    action=action,
                    fields=dict(data),
                    contract_version=mapping.contract_version,
                    blocked_by=blocked_by,
                )
            )
            if action == "delete":
                summary["deleted"] += 1
            else:
                summary[action] += 1
                source_rows.append(dict(data))
            diff_entries.append(
                {
                    "type": row.get("type"),
                    "before": before,
                    "after": after,
                    "action": action,
                    "record_key": record_key,
                }
            )
        if source_rows:
            source_rows_tuple = tuple(source_rows)
        else:
            source_rows_tuple = ()
        write_plan = ForwardWritePlan(
            operations=tuple(operations),
            summary=summary,
            configuration_status=self._configuration_status(
                profile=profile,
                model_mappings=(mapping,),
            ),
            slice_policies={mapping.slug: self._slice_policy_for(mapping)},
            delta_mode=True,
            delta_models=(mapping.slug,),
        )
        return (
            write_plan,
            summary,
            {
                "mode": "delta",
                "rows": diff_entries,
                "operation_count": len(operations),
            },
            source_rows_tuple,
            tuple(diff_entries),
        )

    def run(self, request: ForwardIngestionRequest) -> ForwardIngestionPlan:
        connection = request.connection
        network_id = str(connection.network_id or "").strip()
        if not network_id:
            raise ValueError("Forward network ID is required.")
        model_mappings = get_model_mappings(request.model_names)
        target = NautobotTargetAdapter(model_names=request.model_names)
        target.load()
        source = ForwardSourceAdapter(model_names=request.model_names)
        reports: list[ForwardSyncReport] = []
        current_snapshot_id = self.client.resolve_snapshot_id(
            network_id, request.snapshot_id or connection.snapshot_id
        )
        baseline_snapshot_id = str(
            getattr(request.connection_profile, "last_snapshot_id", "") or ""
        ).strip()
        aggregate_operations: list[ForwardWriteOperation] = []
        aggregate_summary = {
            "create": 0,
            "update": 0,
            "no-change": 0,
            "blocked": 0,
            "deleted": 0,
        }
        diff_detail_slices: dict[str, Any] = {}
        delta_models: list[str] = []
        limit = request.limit or connection.nqe_page_size
        for mapping in model_mappings:
            query_spec = ForwardQuerySpec(
                query_path=mapping.forward_query_path,
                parameters=self._query_parameters_for(mapping, source),
            )
            query_mode = "bundled_nqe"
            query_reference = mapping.forward_query_file
            query_contract_version = mapping.contract_version
            rows: list[dict[str, Any]] = []
            report_rows: list[dict[str, Any]] = []
            notes: tuple[str, ...] = (f"Loaded {mapping.slug} rows from bundled NQE.",)
            resolved_query_reference = ""
            slice_write_plan: ForwardWritePlan
            slice_diff_summary: dict[str, int]
            slice_diff_detail: dict[str, Any]
            diff_fallback_detail: dict[str, Any] | None = None
            try:
                resolved_query_spec = self.client.resolve_query_spec(query_spec)
                query_mode = "bundled_nqe_query_id"
                resolved_query_reference = resolved_query_spec.reference
                if (
                    baseline_snapshot_id
                    and baseline_snapshot_id != current_snapshot_id
                    and (resolved_query_spec.resolved_query_id or resolved_query_spec.query_id)
                ):
                    try:
                        rows = self.client.run_nqe_diff(
                            query_id=resolved_query_spec.resolved_query_id
                            or resolved_query_spec.query_id
                            or "",
                            commit_id=resolved_query_spec.resolved_commit_id
                            or resolved_query_spec.commit_id,
                            parameters=resolved_query_spec.parameters,
                            before_snapshot_id=baseline_snapshot_id,
                            after_snapshot_id=current_snapshot_id,
                            limit=limit,
                            offset=request.offset,
                            fetch_all=request.fetch_all,
                        )
                        query_mode = "bundled_nqe_query_id_diff"
                    except Exception as diff_error:
                        notes = notes + (
                            "Diff execution failed; using query ID-backed full query instead.",
                        )
                        rows = self.client.run_nqe_query(
                            query_spec=resolved_query_spec,
                            network_id=network_id,
                            snapshot_id=current_snapshot_id,
                            limit=limit,
                            offset=request.offset,
                            fetch_all=request.fetch_all,
                            item_format=request.item_format,
                        )
                        query_mode = "bundled_nqe_query_id"
                        diff_fallback_detail = {
                            "mode": "snapshot",
                            "query_mode": query_mode,
                            "query_reference": query_reference,
                            "fallback": "diff-unavailable",
                            "error": str(diff_error),
                            "rows": rows,
                        }
                else:
                    rows = self.client.run_nqe_query(
                        query_spec=resolved_query_spec,
                        network_id=network_id,
                        snapshot_id=current_snapshot_id,
                        limit=limit,
                        offset=request.offset,
                        fetch_all=request.fetch_all,
                        item_format=request.item_format,
                    )
                if query_mode.endswith("_diff"):
                    slice_write_plan, slice_diff_summary, slice_diff_detail, source_rows, report_rows = self._build_delta_plan(
                        mapping=mapping,
                        rows=rows,
                        profile=request.connection_profile,
                    )
                    if source_rows:
                        source.load_rows(mapping.slug, source_rows)
                    delta_models.append(mapping.slug)
                    diff_detail_slices[mapping.slug] = {
                        **slice_diff_detail,
                        "query_mode": query_mode,
                        "query_reference": query_reference,
                        "resolved_query_reference": resolved_query_reference,
                        "summary": dict(slice_write_plan.summary),
                    }
                else:
                    source.load_rows(mapping.slug, rows)
                    slice_source = source.slice_for_model(mapping.slug)
                    slice_target = target.slice_for_model(mapping.slug)
                    slice_write_plan, slice_diff_summary, slice_diff_detail = self._build_full_plan(
                        source=slice_source,
                        target=slice_target,
                        profile=request.connection_profile,
                    )
                    report_rows = rows
                    diff_detail_slices[mapping.slug] = {
                        "mode": "snapshot",
                        "query_mode": query_mode,
                        "query_reference": query_reference,
                        "resolved_query_reference": resolved_query_reference,
                        "rows": rows,
                        "diff_summary": dict(slice_diff_summary),
                        "diff_detail": slice_diff_detail,
                        "summary": dict(slice_write_plan.summary),
                    }
                    if diff_fallback_detail is not None:
                        diff_detail_slices[mapping.slug].update(diff_fallback_detail)
            except Exception:
                query_text = self._query_text_for(mapping)
                rows = self.client.run_nqe_query(
                    query_spec=ForwardQuerySpec(query_text=query_text),
                    network_id=network_id,
                    snapshot_id=current_snapshot_id,
                    limit=limit,
                    offset=request.offset,
                    fetch_all=request.fetch_all,
                    item_format=request.item_format,
                )
                query_mode = "bundled_nqe_inline"
                query_reference = mapping.forward_query_file
                source.load_rows(mapping.slug, rows)
                slice_source = source.slice_for_model(mapping.slug)
                slice_target = target.slice_for_model(mapping.slug)
                slice_write_plan, slice_diff_summary, slice_diff_detail = self._build_full_plan(
                    source=slice_source,
                    target=slice_target,
                    profile=request.connection_profile,
                )
                report_rows = rows
                notes = notes + ("Bundled query path resolution failed; inline NQE was used.",)
                diff_detail_slices[mapping.slug] = {
                    "mode": "snapshot",
                    "query_mode": query_mode,
                    "query_reference": query_reference,
                    "resolved_query_reference": resolved_query_reference,
                    "rows": rows,
                    "diff_summary": dict(slice_diff_summary),
                    "diff_detail": slice_diff_detail,
                    "summary": dict(slice_write_plan.summary),
                }
            aggregate_operations.extend(slice_write_plan.operations)
            aggregate_summary = self._merge_counts(aggregate_summary, slice_write_plan.summary)
            reports.append(
                ForwardSyncReport(
                    mode="preview",
                    source_url=connection.base_url.rstrip("/"),
                    network_id=network_id,
                    snapshot_id=current_snapshot_id,
                    baseline_snapshot_id=baseline_snapshot_id,
                    query_mode=query_mode,
                    query_reference=query_reference,
                    query_contract_version=query_contract_version,
                    row_count=len(report_rows or rows),
                    rows=tuple(report_rows or rows),
                    planned_models=(mapping.slug,),
                    notes=(
                        *notes,
                        *(
                            (f"Diff baseline snapshot: {baseline_snapshot_id}.",)
                            if query_mode.endswith("_diff") and baseline_snapshot_id
                            else ()
                        ),
                    ),
                )
            )
        write_plan = ForwardWritePlan(
            operations=tuple(aggregate_operations),
            summary=aggregate_summary,
            configuration_status=self._configuration_status(
                profile=request.connection_profile,
                model_mappings=model_mappings,
            ),
            slice_policies={
                mapping.slug: self._slice_policy_for(mapping)
                for mapping in model_mappings
            },
            delta_mode=bool(delta_models),
            delta_models=tuple(delta_models),
        )
        diff_detail = {
            "mode": (
                "mixed"
                if delta_models and len(delta_models) != len(model_mappings)
                else "delta"
                if delta_models
                else "snapshot"
            ),
            "baseline_snapshot_id": baseline_snapshot_id,
            "current_snapshot_id": current_snapshot_id,
            "delta_models": list(delta_models),
            "slices": diff_detail_slices,
        }
        return ForwardIngestionPlan(
            source=source,
            target=target,
            reports=tuple(reports),
            write_plan=write_plan,
            diff_summary=dict(aggregate_summary),
            diff_detail=diff_detail,
        )
