"""Ingestion planning for the Forward integration."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from ...models import ForwardConnectionProfileRecord, build_sync_scope_fingerprint
from .adapters import ForwardSourceAdapter, NautobotTargetAdapter
from .client import ForwardClient
from .exceptions import ForwardClientError, ForwardConfigurationError
from .models import ForwardConnectionSettings, ForwardQuerySpec, ForwardSyncReport
from .queries import read_bundled_query_execution_source
from .registry import ForwardModelMapping, get_model_mapping, get_model_mappings
from .write_contract import ForwardWriteContractAdvisor
from .write_path import ForwardWriteOperation, ForwardWritePlan, ForwardWritePlanner


@dataclass(slots=True)
class ForwardIngestionRequest:
    """Inputs for a raw ingestion pass."""

    connection: ForwardConnectionSettings
    model_names: tuple[str, ...] = ()
    fetch_all: bool = True
    limit: int | None = None
    offset: int = 0
    snapshot_id: str | None = None
    connection_profile: ForwardConnectionProfileRecord | None = None
    device_vendors: tuple[str, ...] = ()
    device_types: tuple[str, ...] = ()
    device_models: tuple[str, ...] = ()

    @property
    def filtered_scope(self) -> bool:
        return bool(self.device_vendors or self.device_types or self.device_models)


def _scope_token(value: Any) -> str:
    """Normalize Forward enum strings and operator values for scope comparison."""

    return str(value or "").strip().rsplit(".", 1)[-1].casefold()


@dataclass(frozen=True, slots=True)
class ForwardDeviceScope:
    """Current-snapshot device membership used to scope full and diff rows."""

    device_names: frozenset[str] = frozenset()

    @classmethod
    def from_device_rows(
        cls,
        rows: list[dict[str, Any]],
        request: ForwardIngestionRequest,
    ) -> ForwardDeviceScope:
        allowed_vendors = {_scope_token(value) for value in request.device_vendors}
        allowed_types = {_scope_token(value) for value in request.device_types}
        allowed_models = {_scope_token(value) for value in request.device_models}
        selected: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            if allowed_vendors and _scope_token(row.get("vendor")) not in allowed_vendors:
                continue
            if allowed_types and _scope_token(row.get("device_type")) not in allowed_types:
                continue
            if allowed_models and _scope_token(row.get("model")) not in allowed_models:
                continue
            name = str(row.get("name") or "").strip()
            if name:
                selected.add(name)
        return cls(device_names=frozenset(selected))

    def includes(self, mapping: ForwardModelMapping, row: dict[str, Any]) -> bool:
        """Return whether a raw query row belongs to the selected device closure."""

        if mapping.slug == "devices":
            return str(row.get("name") or "").strip() in self.device_names
        scope_devices = row.get("scope_devices")
        if isinstance(scope_devices, (list, tuple, set, frozenset)):
            return any(str(name or "").strip() in self.device_names for name in scope_devices)
        device_name = str(row.get("device") or "").strip()
        if device_name:
            return device_name in self.device_names
        return False


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
        filtered_scope: bool = False,
    ) -> dict[str, Any]:
        return {
            "profile_provided": profile is not None,
            "write_ready": bool(profile.write_ready) if profile is not None else False,
            "missing_defaults": list(profile.missing_write_defaults())
            if profile is not None
            else [],
            "delete_policy": getattr(profile, "delete_policy", "ignore")
            if profile is not None
            else "ignore",
            "filtered_scope": filtered_scope,
            "missing_reconciliation_enabled": not filtered_scope,
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
        request: ForwardIngestionRequest,
    ) -> dict[str, list[str]]:
        parameters: dict[str, list[str]] = {}
        for parameter_name, source_slugs in mapping.query_parameters.items():
            scoped_values: list[str] = []
            for source_slug in source_slugs:
                scoped_values.extend(self._scope_values_for_source(source, source_slug))
            parameters[parameter_name] = list(dict.fromkeys(scoped_values))
        return parameters

    @staticmethod
    def _filter_rows_for_scope(
        *,
        mapping: ForwardModelMapping,
        rows: list[dict[str, Any]],
        is_diff: bool,
        scope: ForwardDeviceScope | None,
    ) -> tuple[list[dict[str, Any]], int]:
        if scope is None or not mapping.supports_device_filters:
            return rows, 0
        scoped_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            candidate = row
            if is_diff:
                after = row.get("after")
                before = row.get("before")
                candidate = after if isinstance(after, dict) and after else before
                if not isinstance(candidate, dict):
                    continue
            if scope.includes(mapping, candidate):
                scoped_rows.append(row)
        return scoped_rows, len(rows) - len(scoped_rows)

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
        filtered_scope: bool = False,
    ) -> tuple[ForwardWritePlan, dict[str, int], dict[str, Any]]:
        writer = ForwardWritePlanner()
        write_plan = writer.plan(
            source,
            target,
            profile=profile,
            filtered_scope=filtered_scope,
        )
        return write_plan, dict(write_plan.diff_summary), dict(write_plan.diff_detail)

    def _build_delta_plan(
        self,
        *,
        mapping: ForwardModelMapping,
        rows: list[dict[str, Any]],
        profile: ForwardConnectionProfileRecord | None,
        filtered_scope: bool = False,
    ) -> tuple[
        ForwardWritePlan,
        dict[str, int],
        dict[str, Any],
        tuple[dict[str, Any], ...],
        tuple[dict[str, Any], ...],
    ]:
        advisor = ForwardWriteContractAdvisor()
        operations: list[ForwardWriteOperation] = []
        summary = {
            "create": 0,
            "update": 0,
            "deleted": 0,
            "blocked": 0,
            "no-change": 0,
            "filtered_out": 0,
        }
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
            if action == "delete" and filtered_scope:
                summary["filtered_out"] += 1
                diff_entries.append(
                    {
                        "type": row.get("type"),
                        "before": before,
                        "after": after,
                        "action": "filtered-delete-suppressed",
                        "record_key": record_key,
                    }
                )
                continue
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
                filtered_scope=filtered_scope,
            ),
            slice_policies={mapping.slug: self._slice_policy_for(mapping)},
            delta_mode=True,
            delta_models=(mapping.slug,),
            filtered_scope=filtered_scope,
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

    @staticmethod
    def _compute_tiers(
        mappings: tuple[ForwardModelMapping, ...],
    ) -> list[list[ForwardModelMapping]]:
        """Group topologically-ordered mappings into parallel execution tiers.

        A tier boundary is created for both explicit `depends_on` structural
        dependencies and implicit `query_parameters` source-slug dependencies,
        since both require the source adapter to be populated before the query
        parameters can be computed.
        """
        selected_slugs = {m.slug for m in mappings}
        deps_by_slug: dict[str, list[str]] = {}
        for m in mappings:
            param_source_deps = {
                src_slug for src_slugs in m.query_parameters.values() for src_slug in src_slugs
            }
            all_deps = set(m.depends_on) | param_source_deps
            deps_by_slug[m.slug] = [d for d in all_deps if d in selected_slugs]

        # Longest-path levelling with explicit cycle detection. The registry only
        # cycle-checks depends_on, so a cycle introduced via query_parameters must
        # be caught here rather than KeyError-ing or mis-levelling at runtime.
        levels: dict[str, int] = {}
        resolving: set[str] = set()

        def _level_of(slug: str) -> int:
            cached = levels.get(slug)
            if cached is not None:
                return cached
            if slug in resolving:
                raise ForwardConfigurationError(
                    f"Forward model dependency cycle detected involving `{slug}` "
                    "(check depends_on and query_parameters)."
                )
            resolving.add(slug)
            level = 1 + max((_level_of(d) for d in deps_by_slug[slug]), default=0)
            resolving.discard(slug)
            levels[slug] = level
            return level

        for m in mappings:
            _level_of(m.slug)
        max_level = max(levels.values(), default=1)
        tiers: list[list[ForwardModelMapping]] = [[] for _ in range(max_level)]
        for m in mappings:
            tiers[levels[m.slug] - 1].append(m)
        return tiers

    @staticmethod
    def _slice_fetch_error(
        mapping: ForwardModelMapping, exc: ForwardClientError
    ) -> ForwardClientError:
        """Re-raise a slice fetch failure with the failing slice + Forward query
        attributed, so the operator sees *what* broke (domain data only we hold)
        instead of a bare transport error."""
        return ForwardClientError(
            f"slice '{mapping.slug}' (query {mapping.forward_query_file}) failed: {exc}"
        )

    def _fetch_slice(
        self,
        *,
        mapping: ForwardModelMapping,
        parameters: dict[str, list[str]],
        network_id: str,
        current_snapshot_id: str,
        baseline_snapshot_id: str,
        limit: int,
        offset: int,
        fetch_all: bool,
    ) -> tuple[
        list[dict[str, Any]],  # rows
        str,  # query_mode
        str,  # query_reference
        str,  # resolved_query_reference
        tuple[str, ...],  # notes
        bool,  # is_diff
        float,  # query_runtime_ms
        str,  # commit_id
    ]:
        """Run the network I/O for a single slice. Thread-safe — no shared state writes."""
        _t0 = time.perf_counter()

        def _elapsed_ms() -> float:
            return round((time.perf_counter() - _t0) * 1000, 1)

        query_spec = ForwardQuerySpec(
            query_path=mapping.forward_query_path,
            parameters=parameters,
        )
        query_mode = "bundled_nqe_query_id_async"
        query_reference = mapping.forward_query_file
        notes: tuple[str, ...] = (f"Loaded {mapping.slug} rows from bundled NQE.",)
        is_diff = False

        try:
            resolved_query_spec = self.client.resolve_query_spec(query_spec)
        except ForwardClientError:
            resolved_query_spec = ForwardQuerySpec(
                query_text=read_bundled_query_execution_source(mapping.forward_query_file),
                parameters=parameters,
            )
            query_mode = "bundled_nqe_inline_async"
            notes = (
                f"Loaded {mapping.slug} rows from bundled inline NQE because the "
                "published query path was unavailable.",
                "NQE diffs are disabled for this slice until the bundled query is published.",
            )
        resolved_query_reference = resolved_query_spec.reference
        commit_id = str(
            resolved_query_spec.resolved_commit_id or resolved_query_spec.commit_id or ""
        )
        if (
            baseline_snapshot_id
            and baseline_snapshot_id != current_snapshot_id
            and (resolved_query_spec.resolved_query_id or resolved_query_spec.query_id)
        ):
            rows = self.client.run_nqe_diff(
                query_id=resolved_query_spec.resolved_query_id
                or resolved_query_spec.query_id
                or "",
                commit_id=resolved_query_spec.resolved_commit_id or resolved_query_spec.commit_id,
                before_snapshot_id=baseline_snapshot_id,
                after_snapshot_id=current_snapshot_id,
                limit=limit,
                offset=offset,
                fetch_all=fetch_all,
            )
            query_mode = "bundled_nqe_query_id_diff"
            is_diff = True
        else:
            rows = self.client.run_nqe_query(
                query_spec=resolved_query_spec,
                network_id=network_id,
                snapshot_id=current_snapshot_id,
                limit=limit,
                offset=offset,
                fetch_all=fetch_all,
            )

        return (
            rows,
            query_mode,
            query_reference,
            resolved_query_reference,
            notes,
            is_diff,
            _elapsed_ms(),
            commit_id,
        )

    def run(self, request: ForwardIngestionRequest) -> ForwardIngestionPlan:
        connection = request.connection
        network_id = str(connection.network_id or "").strip()
        if not network_id:
            raise ValueError("Forward network ID is required.")
        model_mappings = get_model_mappings(request.model_names)
        current_scope_fingerprint = build_sync_scope_fingerprint(
            model_names=tuple(mapping.slug for mapping in model_mappings),
            device_vendors=request.device_vendors,
            device_types=request.device_types,
            device_models=request.device_models,
        )
        target = NautobotTargetAdapter(model_names=request.model_names)
        target.load()
        source = ForwardSourceAdapter(model_names=request.model_names)
        reports: list[ForwardSyncReport] = []
        current_snapshot_id = self.client.resolve_snapshot_id(
            network_id, request.snapshot_id or connection.snapshot_id
        )
        previous_snapshot_id = str(
            getattr(request.connection_profile, "last_snapshot_id", "") or ""
        ).strip()
        previous_scope_fingerprint = str(
            getattr(request.connection_profile, "last_scope_fingerprint", "") or ""
        ).strip()
        scope_matches = bool(
            previous_scope_fingerprint and previous_scope_fingerprint == current_scope_fingerprint
        )
        baseline_snapshot_id = previous_snapshot_id if scope_matches else ""
        if baseline_snapshot_id and baseline_snapshot_id == current_snapshot_id:
            empty_summary: dict[str, int] = {
                "create": 0,
                "update": 0,
                "no-change": 0,
                "blocked": 0,
                "deleted": 0,
            }
            return ForwardIngestionPlan(
                source=source,
                target=target,
                reports=(),
                write_plan=ForwardWritePlan(
                    configuration_status=self._configuration_status(
                        profile=request.connection_profile,
                        model_mappings=model_mappings,
                        filtered_scope=request.filtered_scope,
                    ),
                    slice_policies={m.slug: self._slice_policy_for(m) for m in model_mappings},
                    filtered_scope=request.filtered_scope,
                    scope_fingerprint=current_scope_fingerprint,
                ),
                diff_summary=empty_summary,
                diff_detail={
                    "mode": "snapshot",
                    "baseline_snapshot_id": baseline_snapshot_id,
                    "current_snapshot_id": current_snapshot_id,
                    "current_scope_fingerprint": current_scope_fingerprint,
                    "previous_scope_fingerprint": previous_scope_fingerprint,
                    "delta_models": [],
                    "skipped": True,
                    "reason": "snapshot unchanged since last sync",
                    "slices": {},
                },
            )
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

        tiers = self._compute_tiers(model_mappings)

        # Warm the NQE query index cache before parallel tier dispatch.
        # All bundled mappings share org:head — one fetch fills the cache so
        # N parallel workers don't race on the same endpoint.
        self.client.get_nqe_repository_query_index(repository="org", commit_id="head")

        device_scope: ForwardDeviceScope | None = None
        scope_query_mode = ""
        if request.filtered_scope:
            try:
                (
                    scope_rows,
                    scope_query_mode,
                    _scope_query_reference,
                    _scope_resolved_reference,
                    _scope_notes,
                    _scope_is_diff,
                    _scope_runtime_ms,
                    _scope_commit_id,
                ) = self._fetch_slice(
                    mapping=get_model_mapping("devices"),
                    parameters={},
                    network_id=network_id,
                    current_snapshot_id=current_snapshot_id,
                    baseline_snapshot_id="",
                    limit=connection.nqe_page_size,
                    offset=0,
                    fetch_all=True,
                )
            except ForwardClientError as exc:
                raise self._slice_fetch_error(get_model_mapping("devices"), exc) from exc
            device_scope = ForwardDeviceScope.from_device_rows(scope_rows, request)

        for tier in tiers:
            # Compute query parameters for each slice in this tier (reads source, sequential).
            tier_params = {m.slug: self._query_parameters_for(m, source, request) for m in tier}

            # Fetch rows for each slice in parallel (pure network I/O, no shared writes).
            if len(tier) > 1:
                # Forward's async submit endpoint becomes unstable when a single
                # sync bursts several expensive executions at once. Two workers
                # preserve useful overlap without triggering tenant-side 500s.
                with ThreadPoolExecutor(max_workers=min(2, len(tier))) as pool:
                    futures = {
                        pool.submit(
                            self._fetch_slice,
                            mapping=m,
                            parameters=tier_params[m.slug],
                            network_id=network_id,
                            current_snapshot_id=current_snapshot_id,
                            baseline_snapshot_id=baseline_snapshot_id,
                            limit=limit,
                            offset=request.offset,
                            fetch_all=request.fetch_all,
                        ): m
                        for m in tier
                    }
                    tier_fetch: dict[str, tuple] = {}
                    for future in as_completed(futures):
                        failed_mapping = futures[future]
                        try:
                            tier_fetch[failed_mapping.slug] = future.result()
                        except ForwardClientError as exc:
                            raise self._slice_fetch_error(failed_mapping, exc) from exc
            else:
                m = tier[0]
                try:
                    slice_result = self._fetch_slice(
                        mapping=m,
                        parameters=tier_params[m.slug],
                        network_id=network_id,
                        current_snapshot_id=current_snapshot_id,
                        baseline_snapshot_id=baseline_snapshot_id,
                        limit=limit,
                        offset=request.offset,
                        fetch_all=request.fetch_all,
                    )
                except ForwardClientError as exc:
                    raise self._slice_fetch_error(m, exc) from exc
                tier_fetch = {m.slug: slice_result}

            # Process results in topo order (mutates source — must be sequential).
            for mapping in tier:
                (
                    rows,
                    query_mode,
                    query_reference,
                    resolved_query_reference,
                    notes,
                    is_diff,
                    query_runtime_ms,
                    commit_id,
                ) = tier_fetch[mapping.slug]
                rows, scope_filtered_count = self._filter_rows_for_scope(
                    mapping=mapping,
                    rows=rows,
                    is_diff=is_diff,
                    scope=device_scope,
                )
                if scope_filtered_count:
                    notes = (
                        *notes,
                        f"Excluded {scope_filtered_count} row(s) outside the configured device scope.",
                    )
                query_contract_version = mapping.contract_version
                report_rows: list[dict[str, Any]] = []
                slice_write_plan: ForwardWritePlan
                slice_diff_summary: dict[str, int]
                slice_diff_detail: dict[str, Any]

                if is_diff:
                    (
                        slice_write_plan,
                        slice_diff_summary,
                        slice_diff_detail,
                        source_rows,
                        report_rows,
                    ) = self._build_delta_plan(
                        mapping=mapping,
                        rows=rows,
                        profile=request.connection_profile,
                        filtered_scope=request.filtered_scope,
                    )
                    if source_rows:
                        source.load_rows(mapping.slug, source_rows)
                    delta_models.append(mapping.slug)
                    diff_detail_slices[mapping.slug] = {
                        **slice_diff_detail,
                        "query_mode": query_mode,
                        "query_reference": query_reference,
                        "resolved_query_reference": resolved_query_reference,
                        "query_runtime_ms": query_runtime_ms,
                        "commit_id": commit_id,
                        "scope_filtered_count": scope_filtered_count,
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
                        filtered_scope=request.filtered_scope,
                    )
                    report_rows = rows
                    diff_detail_slices[mapping.slug] = {
                        "mode": "snapshot",
                        "query_mode": query_mode,
                        "query_reference": query_reference,
                        "resolved_query_reference": resolved_query_reference,
                        "query_runtime_ms": query_runtime_ms,
                        "commit_id": commit_id,
                        "scope_filtered_count": scope_filtered_count,
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
                filtered_scope=request.filtered_scope,
            ),
            slice_policies={
                mapping.slug: self._slice_policy_for(mapping) for mapping in model_mappings
            },
            delta_mode=bool(delta_models),
            delta_models=tuple(delta_models),
            filtered_scope=request.filtered_scope,
            scope_fingerprint=current_scope_fingerprint,
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
            "previous_snapshot_id": previous_snapshot_id,
            "current_scope_fingerprint": current_scope_fingerprint,
            "previous_scope_fingerprint": previous_scope_fingerprint,
            "scope_changed": bool(
                previous_scope_fingerprint
                and previous_scope_fingerprint != current_scope_fingerprint
            ),
            "filtered_scope": request.filtered_scope,
            "selected_device_count": len(device_scope.device_names) if device_scope else 0,
            "scope_query_mode": scope_query_mode,
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
